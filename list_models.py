"""Ask the Models API which models this API key can use, and compare with config.py.

Listing models is free. Usage:
  python3 list_models.py
"""

import os
import sys

import anthropic

import config

if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ANTHROPIC_API_KEY is not set. See 'Setting your API key' in README.md.")

client = anthropic.Anthropic()
available = [m.id for m in client.models.list()]  # the SDK fetches every page for us

print("Models available to this key:")
for model_id in available:
    print(f"  {model_id}")

print("\nModels in config.py:")
for size, model_id in config.MODELS.items():
    status = "OK" if model_id in available else "NOT AVAILABLE to this key"
    print(f"  {size:<6} {model_id:<20} {status}")
