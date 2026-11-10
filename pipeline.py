"""Bounded, evidence-only pipeline shared by real and simulated experiments."""
import json, os, time, re, threading, pathlib, requests
from relay import Retrieval
SETTINGS={'small':(80,2),'medium':(160,3),'large':(240,4)}
REFUSAL='The papers do not establish a verified answer to this question.'
class ServiceError(Exception):
 def __init__(self,status,retry_after=0,daily=False): self.status=status; self.retry_after=retry_after; self.daily=daily
class Groq:
 def call(self,prompt,trace,deadline):
  start=time.perf_counter(); event={'stage':'model','start':start}; trace.append(event)
  try:
   with requests.post('https://api.groq.com/openai/v1/chat/completions',headers={'Authorization':'Bearer '+os.environ['GROQ_API_KEY']},json={'model':'openai/gpt-oss-20b','messages':[{'role':'user','content':prompt}],'temperature':0,'reasoning_effort':'low','max_tokens':650,'stream':True,'stream_options':{'include_usage':True}},stream=True,timeout=(5,min(15,max(.1,deadline-time.perf_counter())))) as r:
    event['http_status']=r.status_code; event['headers']={k:v for k,v in r.headers.items() if k.lower().startswith(('x-ratelimit','retry-after'))}
    if not r.ok:
     event['body']=r.text
     raise ServiceError('rate_limited' if r.status_code==429 else 'error',float(r.headers.get('retry-after',1)),bool(re.search(r'per day|daily|\bTPD\b|\bRPD\b',r.text,re.I)))
    text=''
    for line in r.iter_lines(chunk_size=1):
     if time.perf_counter()>deadline: raise ServiceError('timeout')
     if not line.startswith(b'data: '): continue
     if line[6:]==b'[DONE]': break
     d=json.loads(line[6:]); event['usage']=d.get('usage') or event.get('usage',{})
     for c in d.get('choices',[]):
      piece=c.get('delta',{}).get('content') or ''
      if piece and 'first_token_ms' not in event: event['first_token_ms']=(time.perf_counter()-start)*1000
      text+=piece
    event['response']=text
    return text
  except requests.Timeout: raise ServiceError('timeout')
  except requests.RequestException: raise ServiceError('error')
  finally: event['total_ms']=(time.perf_counter()-start)*1000

class Pipeline:
 def __init__(self,service,capacity=2,queue_limit=6,deadline=12,retry=True):
  self.service=service; self.slots=threading.BoundedSemaphore(capacity); self.lock=threading.Lock(); self.waiters=0; self.queue_limit=queue_limit; self.deadline=deadline; self.retry=retry
  self.retrievers={k:Retrieval(*v) for k,v in SETTINGS.items()}
 def run(self,q,setting='medium'):
  start=time.perf_counter(); deadline=start+self.deadline; trace=[]
  result={'question_id':q['id'],'question':q['question'],'start_time':time.time(),'status':'ok','retries':0,'tokens_in':0,'tokens_out':0,'first_token_ms':None,'answer':REFUSAL,'answer_grade':'refused_wrongly','waiting_ms':0,'working_ms':0,'retrying_ms':0,'queue_length':0,'trace':trace}
  acquired=False
  try:
   with self.lock:
    if self.waiters>=self.queue_limit: raise ServiceError('rate_limited')
    self.waiters+=1; result['queue_length']=self.waiters
   acquired=self.slots.acquire(timeout=max(0,deadline-time.perf_counter()))
   with self.lock: self.waiters-=1
   result['waiting_ms']=(time.perf_counter()-start)*1000
   if not acquired: raise ServiceError('timeout')
   def call(prompt):
    for attempt in range(2):
     try: return self.service.call(prompt,trace,deadline)
     except ServiceError as e:
      delay=max(.1,e.retry_after)+.05
      if not self.retry or attempt or e.daily or e.status not in ('rate_limited','error') or time.perf_counter()+delay+1>=deadline: raise
      result['retries']+=1; t=time.perf_counter(); time.sleep(delay); result['retrying_ms']+=(time.perf_counter()-t)*1000
   query=call('Return only a concise search query for this question, preserving names and technical terms: '+q['question'])
   t=time.perf_counter(); evidence=self.retrievers[setting].search(q['question']+' '+query)
   trace.append({'stage':'retrieval_tool','start':t,'total_ms':(time.perf_counter()-t)*1000})
   prompt='Select an exact verbatim quote from ONE evidence passage that directly answers the question. Do not infer, combine, or paraphrase. If unsupported return {"id":null,"quote":null}. Otherwise return JSON only: {"id":"exact passage id","quote":"verbatim excerpt"}.\nQuestion: '+q['question']+'\nEvidence: '+json.dumps(evidence)
   draft=call(prompt); result['draft']=draft; result['evidence']=evidence
   try:
    obj=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',draft.strip())); quote=obj.get('quote'); ident=obj.get('id')
    passage=next((p for p in evidence if p['id']==ident),None)
    if quote and passage and quote in passage['text']:
     result['answer']=quote+' ['+ident+']'
   except (ValueError,TypeError,AttributeError): pass
   if time.perf_counter()>deadline: raise ServiceError('timeout')
   result['first_token_ms']=(time.perf_counter()-start)*1000
  except ServiceError as e: result['status']=e.status; result['error_daily']=e.daily
  except Exception as e: result['status']='error'; result['error']=type(e).__name__+': '+str(e)
  finally:
   if acquired: self.slots.release()
   result['total_ms']=(time.perf_counter()-start)*1000
   result['working_ms']=max(0,result['total_ms']-result['waiting_ms']-result['retrying_ms'])
   for ev in trace:
    u=ev.get('usage',{}); result['tokens_in']+=u.get('prompt_tokens',0); result['tokens_out']+=u.get('completion_tokens',0)
  # Provisional rubric only; review answer text and original page before finalizing grades.
  refusal=result['answer']==REFUSAL
  if refusal: result['answer_grade']='refused_correctly' if q['paper'] is None else 'refused_wrongly'
  else: result['answer_grade']='correct' if q['paper'] and q['paper'] in result['answer'] and all(t.lower() in result['answer'].lower() for t in q['expected_terms']) else 'wrong'
  return result
