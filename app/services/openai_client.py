import os
from functools import lru_cache
from openai import OpenAI


@lru_cache()
def get_openai_client() -> OpenAI:
    api_key = os.environ["OPENAI_API_KEY"]  
    return OpenAI(api_key=api_key)