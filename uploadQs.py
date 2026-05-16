import json
import csv
from datetime import datetime
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

raw_url = os.environ["SUPABASE_URL"].strip()
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip()

# supabase-py の create_client には、https://xxxxx.supabase.co だけを渡します。
# .env に /rest/v1 まで入っている場合は取り除きます。
SUPABASE_URL = raw_url.rstrip("/")
if SUPABASE_URL.endswith("/rest/v1"):
    SUPABASE_URL = SUPABASE_URL[: -len("/rest/v1")]

print("SUPABASE_URL check:", SUPABASE_URL)
print("KEY check:", SUPABASE_SERVICE_ROLE_KEY[:12] + "..." + SUPABASE_SERVICE_ROLE_KEY[-6:])

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# このスクリプトと同じフォルダ内の JSON ファイルを自動検出します。
# questions.json があれば最優先で使用し、なければ最新更新日の JSON を使用します。
# 設定用 JSON などを誤って拾わないように、配列形式の JSON のみを候補にします。
script_dir = Path(__file__).resolve().parent
json_candidates = []

for path in sorted(script_dir.glob("*.json")):
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[SKIP] invalid json: {path.name} ({e})")
        continue
    except OSError as e:
        print(f"[SKIP] cannot read: {path.name} ({e})")
        continue

    if isinstance(data, list):
        json_candidates.append((path, data))
    else:
        print(f"[SKIP] not a questions array: {path.name}")

if not json_candidates:
    raise FileNotFoundError("このスクリプトと同じフォルダ内に、問題配列形式の JSON ファイルが見つかりません。")

questions_json = next(((path, data) for path, data in json_candidates if path.name == "questions.json"), None)

if questions_json is None:
    questions_json = max(json_candidates, key=lambda item: item[0].stat().st_mtime)

questions_path, questions = questions_json
print(f"Using questions file: {questions_path.name}")
print(f"Loaded questions: {len(questions)}")


def get_rank_tier(difficulty_tier, knowledge_level):
    """difficulty_tier × knowledge_level から rank tier A〜D を求める。"""
    difficulty_tier = (difficulty_tier or "").strip().lower()
    knowledge_level = (knowledge_level or "").strip().lower()

    tier_map = {
        ("beginner", "standard"): "D",
        ("intermediate", "common"): "D",
        ("intermediate", "standard"): "C",
        ("advanced", "common"): "C",
        ("beginner", "advanced"): "B",
        ("advanced", "standard"): "B",
        ("intermediate", "advanced"): "A",
        ("advanced", "advanced"): "A",
    }
    return tier_map.get((difficulty_tier, knowledge_level), "")


rows = []
answer_log_rows = []
skipped = 0
upload_timestamp = datetime.now().isoformat(timespec="seconds")

for q in questions:
    question_id = q.get("id") or q.get("question_id")
    question_text = q.get("text") or q.get("question_text") or q.get("questionText")
    answer_display = q.get("displayAnswer") or q.get("answer_display") or q.get("answerDisplay") or q.get("answer")
    answer_normalized = q.get("normalizedAnswer") or q.get("answer_normalized") or q.get("answerNormalized")
    answer_chars = q.get("answerChars") or q.get("answer_chars")

    if not question_id or not question_text or not answer_display or not answer_normalized or not answer_chars:
        skipped += 1
        print(f"[SKIP] missing required field: {q}")
        continue

    category = q.get("category", "General Knowledge")
    difficulty_tier = q.get("difficulty_tier", q.get("difficultyTier", "beginner"))
    knowledge_level = q.get("knowledge_level", q.get("knowledgeLevel", "common"))
    rank_tier = get_rank_tier(difficulty_tier, knowledge_level)

    rows.append({
        "id": question_id,
        "category": category,
        "difficulty_tier": difficulty_tier,
        "knowledge_level": knowledge_level,
        "question_text": question_text,
        "answer_display": answer_display,
        "answer_normalized": answer_normalized,
        "answer_chars": answer_chars,
        "language": q.get("language", "en"),
        "is_active": q.get("is_active", True),
    })

    answer_log_rows.append({
        "id": question_id,
        "source_file": questions_path.name,
        "category": category,
        "difficulty_tier": difficulty_tier,
        "knowledge_level": knowledge_level,
        "rank_tier": rank_tier,
        "displayAnswer": answer_display,
        "normalizedAnswer": answer_normalized,
        "uploaded_at": upload_timestamp,
    })

if not rows:
    raise ValueError("アップロードできる問題がありません。questions.json の形式を確認してください。")

batch_size = 500

for i in range(0, len(rows), batch_size):
    batch = rows[i:i + batch_size]
    supabase.table("questions").upsert(batch, on_conflict="id").execute()
    print(f"uploaded {i + len(batch)} / {len(rows)}")

# Supabase への upsert が成功した後、今回アップロードした問題の回答・難易度・tier を CSV に記録します。
# 同じ id が既にCSVにある場合は重複追記しません。
existing_quiz_path = script_dir / "existing_quiz.csv"
answer_log_fieldnames = [
    "id",
    "source_file",
    "category",
    "difficulty_tier",
    "knowledge_level",
    "rank_tier",
    "displayAnswer",
    "normalizedAnswer",
    "uploaded_at",
]

existing_ids = set()
if existing_quiz_path.exists():
    with existing_quiz_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            existing_id = row.get("id")
            if existing_id:
                existing_ids.add(existing_id)

new_answer_log_rows = [row for row in answer_log_rows if row["id"] not in existing_ids]

with existing_quiz_path.open("a", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=answer_log_fieldnames)
    if f.tell() == 0:
        writer.writeheader()
    writer.writerows(new_answer_log_rows)

print("done")
print(f"uploaded total: {len(rows)}")
print(f"skipped total : {skipped}")
print(f"answer log csv : {existing_quiz_path.name}")
print(f"answer log added: {len(new_answer_log_rows)}")
print(f"answer log skipped existing id: {len(answer_log_rows) - len(new_answer_log_rows)}")