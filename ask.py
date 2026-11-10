"""Interactive entry point for the measured pipeline."""
import argparse,json
from pipeline import Pipeline,Groq
p=argparse.ArgumentParser();p.add_argument('question');p.add_argument('--setting',choices=['small','medium','large'],default='large');a=p.parse_args()
r=Pipeline(Groq()).run({'id':'interactive','question':a.question,'paper':None,'expected_terms':[]},a.setting)
if r['status']=='ok':print(r['answer'])
elif r.get('error_daily'):print("Today's model budget is exhausted. I cannot verify an answer right now. Please try again after the provider budget resets; I have not queued a background answer.")
else:print('The service is temporarily unavailable. I cannot verify an answer within the deadline. Please try again later.')
