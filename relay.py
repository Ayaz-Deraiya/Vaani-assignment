"""Evidence-first research assistant. Run: python relay.py 'your question'."""
import argparse, collections, json, math, os, pathlib, re, time
import requests

STOP=set('the a an is are of to in and what how does for with on it'.split())
def words(s): return set(re.findall(r'[a-z0-9]+',s.lower()))-STOP

class Retrieval:
    def __init__(self,size=220,k=4):
        self.k=k; self.chunks=[]
        for page in json.loads(pathlib.Path('data/pages.json').read_text(encoding='utf-8')):
            tokens=page['text'].split()
            for offset in range(0,len(tokens),max(1,size-40)):
                text=' '.join(tokens[offset:offset+size])
                self.chunks.append(dict(id=f"{page['paper']}:p{page['page']}:w{offset}",text=text))
        self.df=collections.Counter(w for c in self.chunks for w in words(c['text']))
    def search(self,q):
        query=words(q)
        def score(c):
            return sum(math.log(1+len(self.chunks)/(1+self.df[w])) for w in query & words(c['text']))
        return sorted(self.chunks,key=score,reverse=True)[:self.k]

class Groq:
    def __init__(self):
        self.key=os.environ.get('GROQ_API_KEY')
        if not self.key: raise RuntimeError('Configure GROQ_API_KEY locally before real runs.')
        self.model=os.environ.get('GROQ_MODEL','openai/gpt-oss-20b')
    def call(self,prompt,trace):
        start=time.perf_counter()
        r=requests.post('https://api.groq.com/openai/v1/chat/completions',headers={'Authorization':'Bearer '+self.key},json={'model':self.model,'messages':[{'role':'user','content':prompt}],'temperature':0,'max_tokens':1200,'reasoning_effort':'low','stream':True,'stream_options':{'include_usage':True}},stream=True,timeout=(5,25))
        event={'status':r.status_code,'headers':{k:v for k,v in r.headers.items() if k.lower().startswith(('x-ratelimit','retry-after'))}}
        trace.append(event)

        if not r.ok:
            event['body']=r.text
            pathlib.Path('output/provider-error.json').write_text(json.dumps(event),encoding='utf-8')
        r.raise_for_status(); result=''
        for line in r.iter_lines():
            if not line.startswith(b'data: '): continue
            payload=line[6:]
            if payload==b'[DONE]': break
            part=json.loads(payload)
            if part.get('usage'): event['usage']=part['usage']
            for choice in part.get('choices',[]):
                piece=choice.get('delta',{}).get('content') or ''
                if piece and 'first_token_ms' not in event: event['first_token_ms']=(time.perf_counter()-start)*1000
                result+=piece
        event['total_ms']=(time.perf_counter()-start)*1000
        return result

def answer(question,size=220,k=4):
    trace=[]; model=Groq(); start=time.perf_counter()
    # Model routing, retrieval tool, drafting, verification, refusal branch.
    query=model.call('Rewrite as a short search query without adding facts. Return only the query: '+question,trace)
    evidence=Retrieval(size,k).search(query)
    context=json.dumps(evidence)
    draft=model.call('Answer only using the evidence. Cite each claim with the exact [id]. If unsupported say: The papers do not establish this.\nQuestion: '+question+'\nEvidence: '+context,trace)
    verdict=model.call('Check every factual claim and citation against the evidence. Reply only PASS if fully supported and responsive; otherwise FAIL.\nQuestion: '+question+'\nAnswer: '+draft+'\nEvidence: '+context,trace)
    draft=draft.replace(chr(0x3010),'[').replace(chr(0x3011),']')
    ids=set(re.findall(r'\[([^\]]+)\]',draft)); allowed={c['id'] for c in evidence}
    safe=verdict.strip()=='PASS' and bool(ids) and ids<=allowed
    response=draft if safe else 'The papers do not establish a verified answer to this question.'
    # Nothing is exposed until verification; user TTFT includes all checks.
    elapsed=(time.perf_counter()-start)*1000
    return {'question':question,'answer':response,'first_token_ms':elapsed,'total_ms':elapsed,'trace':trace,'evidence':evidence,'draft':draft,'verdict':verdict}

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('question'); p.add_argument('--size',type=int,default=220); p.add_argument('--pieces',type=int,default=4); a=p.parse_args()
    result=answer(a.question,a.size,a.pieces)
    pathlib.Path('output').mkdir(exist_ok=True)
    with open('output/real-traces.jsonl','a',encoding='utf-8') as f: f.write(json.dumps(result)+'\n')
    print(result['answer'])
