import os
import asyncio
import time
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_POPULAR
from flask import Flask, request, jsonify, render_template
from twikit import Client
from langdetect import detect, DetectorFactory

# Set seed for langdetect to ensure consistent results
DetectorFactory.seed = 0

# 1. Setup Flask & Models
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
app = Flask(__name__)
torch.set_num_threads(4)
device = torch.device("cpu")

print("Loading model and tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(".")
model = AutoModelForSequenceClassification.from_pretrained(".")
model.to(device)
model.eval()

def analyze_toxicity(text):
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=128).to(device)
    with torch.no_grad():
        outputs = model(**inputs)
    probs = F.softmax(outputs.logits, dim=-1)[0].tolist()
    bullying_score = probs[1] * 100
    label = "BULLYING" if bullying_score > 50 else "SAFE"
    return label, bullying_score

# --- Twitter Helper ---
async def fetch_twitter_replies_async(tweet_id, max_replies):
    client = Client('en-US')
    try:
        client.load_cookies('cookies.json')
    except Exception as e:
        raise Exception("Could not load cookies.json.")
        
    search_query = f"conversation_id:{tweet_id}"
    replies = await client.search_tweet(search_query, 'Latest', count=20)
    
    raw_texts = []
    if not replies: return raw_texts

    total_fetched = 0
    while total_fetched < max_replies:
        for reply in replies:
            if total_fetched >= max_replies: break
            text = reply.text.replace('\n', ' ').strip()
            
            if text:
                try:
                    # ONLY add the text if it is detected as exactly English ('en')
                    if detect(text) == 'en':
                        raw_texts.append(text)
                        total_fetched += 1
                except Exception:
                    # Skip if text is purely emojis/symbols and throws an error
                    pass

        if total_fetched < max_replies:
            time.sleep(1.5)
            try:
                replies = await replies.next()
            except Exception:
                break
            if not replies: break
    return raw_texts

# 2. Web Routes
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/api/mode1", methods=["POST"])
def mode1():
    data = request.json
    text = data.get("text", "")
    label, score = analyze_toxicity(text)
    return jsonify({"label": label, "score": round(score, 1)})

# --- UPDATED YOUTUBE ROUTE ---
@app.route("/api/mode2", methods=["POST"])
def mode2():
    data = request.json
    url = data.get("url", "")
    count = int(data.get("count", 50))
    
    downloader = YoutubeCommentDownloader()
    comments = []
    bullying_count = 0
    safe_count = 0
    
    try:
        generator = downloader.get_comments_from_url(url, sort_by=SORT_BY_POPULAR)
        for comment in generator:
            if len(comments) >= count: break
            text = comment['text']
            
            try:
                # ONLY process the text if it is detected as exactly English
                if detect(text) == 'en':
                    label, score = analyze_toxicity(text)
                    comments.append({"text": text, "label": label, "score": round(score, 1)})
                    
                    if label == "BULLYING":
                        bullying_count += 1
                    else:
                        safe_count += 1
            except Exception:
                # Skip if text is purely emojis/symbols and throws an error
                pass
                
    except Exception as e:
        return jsonify({"error": str(e)}), 400
        
    total = bullying_count + safe_count
    toxic_percent = (bullying_count / total * 100) if total > 0 else 0
    
    if toxic_percent > 40: verdict = "HIGHLY TOXIC ENVIRONMENT"
    elif toxic_percent > 15: verdict = "MODERATELY TOXIC"
    else: verdict = "SAFE COMMUNITY"
        
    return jsonify({
        "comments": comments,
        "summary": { "total": total, "toxic": bullying_count, "safe": safe_count, "toxic_percent": round(toxic_percent, 1), "verdict": verdict }
    })

# --- TWITTER ROUTE ---
@app.route("/api/mode4", methods=["POST"])
def mode4():
    data = request.json
    url = data.get("url", "")
    count = int(data.get("count", 50))
    
    try:
        tweet_id = url.split('/')[-1].split('?')[0]
        if not tweet_id.isdigit(): return jsonify({"error": "Invalid Twitter URL."}), 400
    except Exception: return jsonify({"error": "Malformed Twitter URL"}), 400

    try:
        raw_replies = asyncio.run(fetch_twitter_replies_async(tweet_id, count))
    except Exception as e: return jsonify({"error": str(e)}), 500
        
    if not raw_replies: return jsonify({"error": "No replies found or rate limit reached."}), 404

    comments = []
    bullying_count = 0
    safe_count = 0
    
    for text in raw_replies:
        label, score = analyze_toxicity(text)
        comments.append({"text": text, "label": label, "score": round(score, 1)})
        if label == "BULLYING": bullying_count += 1
        else: safe_count += 1
            
    total = bullying_count + safe_count
    toxic_percent = (bullying_count / total * 100) if total > 0 else 0
    
    if toxic_percent > 40: verdict = "HIGHLY TOXIC ENVIRONMENT"
    elif toxic_percent > 15: verdict = "MODERATELY TOXIC"
    else: verdict = "SAFE COMMUNITY"
    
    return jsonify({
        "comments": comments,
        "summary": { "total": total, "toxic": bullying_count, "safe": safe_count, "toxic_percent": round(toxic_percent, 1), "verdict": verdict }
    })

if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)
