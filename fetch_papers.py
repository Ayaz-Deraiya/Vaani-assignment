import pathlib, requests, pymupdf, json
out=[]
for ident in ['1706.03762v7','2410.00037v1','2507.07955v2']:
 p=pathlib.Path('data')/(ident+'.pdf')
 r=requests.get('https://arxiv.org/pdf/'+ident,timeout=90); r.raise_for_status(); p.write_bytes(r.content)
 d=pymupdf.open(p)
 out.extend({'paper':ident,'page':i+1,'text':page.get_text()} for i,page in enumerate(d))
pathlib.Path('data/pages.json').write_text(json.dumps(out),encoding='utf-8')
print('Fetched',len(out),'pages')
