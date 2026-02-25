import os
from google import genai
from google.genai import types
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

class Agent:
    def __init__(self, role: str, system_prompt: str):
        self.role = role
        self.system_prompt = system_prompt
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        
        self.config = types.GenerateContentConfig(
            system_instruction=self.system_prompt
        )
        self.chat_session = self.client.chats.create(
            model='gemini-2.5-flash',
            config=self.config
        )

    def chat(self, user_message: str) -> str:
        response = self.chat_session.send_message(user_message)
        return response.text

    def reset(self):
        self.chat_session = self.client.chats.create(
            model='gemini-2.5-flash',
            config=self.config
        )
