import os
import sys
import transformers

MODEL = "cross-encoder/ms-marco-TinyBERT-L-2-v2"

if os.path.exists("data/cross_encoder/"):
    print("data/cross_encoder/ already exists. Exiting...")
    sys.exit()

os.system("mkdir -p data/cross_encoder")

model = transformers.AutoModelForSequenceClassification.from_pretrained(MODEL)
tokenizer = transformers.AutoTokenizer.from_pretrained(MODEL)

model.save_pretrained("data/cross_encoder")
tokenizer.save_pretrained("data/cross_encoder")
