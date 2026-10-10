"""
Loads .env (AWS and Together AI credentials) before any test runs.

Library code only reads the environment; entry points in src/ decide where it comes from.
"""
from dotenv import load_dotenv

load_dotenv()