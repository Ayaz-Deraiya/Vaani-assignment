import unittest,time,json
from pipeline import Pipeline,REFUSAL,ServiceError
Q={'id':'test','question':'How many encoder layers are used?', 'paper':'1706.03762v7','expected_terms':['6']}
class Fake:
 def __init__(self,quote): self.quote=quote; self.calls=0
 def call(self,prompt,trace,deadline):
  self.calls+=1
  if self.calls==1: return 'encoder layers'
  ev=json.loads(prompt.split('\nEvidence: ')[1]); return json.dumps({'id':ev[0]['id'],'quote': self.quote if self.quote is not None else ev[0]['text'][:40]})
class Fail:
 def __init__(self,daily=False): self.daily=daily; self.calls=0
 def call(self,*args): self.calls+=1; raise ServiceError('rate_limited',.01,self.daily)
class Tests(unittest.TestCase):
 def test_fabricated_quote_refused(self): self.assertEqual(Pipeline(Fake('invented unsupported text')).run(Q)['answer'],REFUSAL)
 def test_exact_quote_accepted(self): self.assertNotEqual(Pipeline(Fake(None)).run(Q)['answer'],REFUSAL)
 def test_daily_never_retried(self):
  f=Fail(True); r=Pipeline(f).run(Q); self.assertEqual(f.calls,1); self.assertEqual(r['status'],'rate_limited')
 def test_retry_is_bounded(self):
  f=Fail(); r=Pipeline(f).run(Q); self.assertEqual(f.calls,2); self.assertEqual(r['retries'],1)
 def test_queue_rejects(self):
  p=Pipeline(Fake(None),queue_limit=0); self.assertEqual(p.run(Q)['status'],'rate_limited')
 def test_deadline_wait(self):
  p=Pipeline(Fake(None),capacity=1,deadline=.05); p.slots.acquire(); r=p.run(Q); p.slots.release(); self.assertEqual(r['status'],'timeout'); self.assertIsNone(r['first_token_ms'])
if __name__=='__main__': unittest.main()
