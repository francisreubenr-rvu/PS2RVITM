"""interview: a scripted question list, deterministic reading first, a grounded AI fallback, and the plan at the end.

The model never writes a question. It only extracts the asked field from the owner's words, and code rejects
any number, date or weekday that the owner did not say.
"""
from __future__ import annotations

from app.agnes import text_ready

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import plan as plan_module
from app import speech
from app.agnes import AgnesError
from app import languages
from app.config import CHANNELS, LANGS
from app.db import Database
from app.schemas import OfferFacts
from app.service import Service, ServiceError, now
from app.worker import parse_json_object

router = APIRouter()

SCHEMA = """
CREATE TABLE IF NOT EXISTS interview_session (
  id TEXT PRIMARY KEY,
  lang TEXT NOT NULL,
  campaign_id TEXT,
  clarify TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interview_answer (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  field TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  choices TEXT NOT NULL,
  source TEXT NOT NULL,
  value TEXT,
  status TEXT NOT NULL,
  reason TEXT,
  ts TEXT NOT NULL,
  seq INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_interview_answer_session ON interview_answer(session_id, seq);
"""


def ensure_schema(db: Database) -> None:
    db.ensure(SCHEMA)


# ---------------------------------------------------------------- the script

BUSINESS_TYPES = ["cafe", "restaurant", "bakery", "salon", "boutique", "gym", "clinic", "coaching", "other"]
GOALS = ["more_walkins", "promote_offer", "launch_product", "announce_opening", "grow_followers"]
OFFER_TYPES = ["percent_off", "fixed_price", "buy_one_get_one", "free_item", "no_offer"]
AUDIENCES = ["students", "office_workers", "families", "regulars", "tourists", "nearby_residents"]
TONES = ["friendly", "warm_local", "playful", "straightforward"]
LANGUAGE_LABELS = {l["code"]: l["native"] for l in languages.LANGUAGES}
DAY_LABELS = {
    "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday",
    "sat": "Saturday", "sun": "Sunday", "weekend": "Weekend", "weekdays": "Weekdays", "every_day": "Every day",
}


def _label(value: str) -> str:
    return value.replace("_", " ").capitalize()


OPTIONS: dict[str, list[dict[str, str]]] = {
    "business_type": [{"value": v, "label": _label(v)} for v in BUSINESS_TYPES],
    "goal": [{"value": v, "label": _label(v)} for v in GOALS],
    "offer_type": [{"value": v, "label": _label(v)} for v in OFFER_TYPES],
    "days": [{"value": v, "label": DAY_LABELS[v]} for v in speech.DAY_OPTIONS],
    "audiences": [{"value": v, "label": _label(v)} for v in AUDIENCES],
    "languages": [{"value": v, "label": LANGUAGE_LABELS[v]} for v in LANGS],
    "channels": [{"value": v, "label": _label(v)} for v in CHANNELS],
    "tone": [{"value": v, "label": _label(v)} for v in TONES],
}


@dataclass(frozen=True)
class Q:
    id: str
    field: str
    kind: str
    required: bool
    prompt: dict[str, str]
    hint: str
    when: Callable[[dict[str, Any]], bool] = field(default=lambda f: True)


def _v(fields: dict[str, Any], name: str) -> Any:
    return (fields.get(name) or {}).get("value")


def _grow(f: dict) -> bool:
    return _v(f, "goal") == "grow_followers"


SCRIPT: tuple[Q, ...] = (
    Q("business_name", "business_name", "text", True,
      {"en": "What is your business called?", "hi": "आपके बिज़नेस का नाम क्या है?", "kn": "ನಿಮ್ಮ ವ್ಯಾಪಾರದ ಹೆಸರು ಏನು?"},
      "Say or type the name only."),
    Q("business_type", "business_type", "single", True,
      {"en": "What kind of business is it?", "hi": "यह किस तरह का बिज़नेस है?", "kn": "ಇದು ಯಾವ ರೀತಿಯ ವ್ಯಾಪಾರ?"},
      "Pick one."),
    Q("area", "area", "text", True,
      {"en": "Which city or area is it in?", "hi": "यह किस शहर या इलाके में है?", "kn": "ಇದು ಯಾವ ನಗರ ಅಥವಾ ಪ್ರದೇಶದಲ್ಲಿದೆ?"},
      "Say the locality and the city."),
    Q("goal", "goal", "single", True,
      {"en": "What do you want from this campaign?", "hi": "इस कैंपेन से आप क्या चाहते हैं?", "kn": "ಈ ಅಭಿಯಾನದಿಂದ ನಿಮಗೇನು ಬೇಕು?"},
      "Pick the main goal."),
    Q("offer_type_early", "offer_type", "single", True,
      {"en": "Is there an offer? What kind?", "hi": "क्या कोई ऑफ़र है? किस तरह का?", "kn": "ಯಾವುದಾದರೂ ಆಫರ್ ಇದೆಯೇ? ಯಾವ ರೀತಿಯದು?"},
      "Pick one, or no offer.", when=_grow),
    Q("offer_item", "offer_item", "text", True,
      {"en": "Which item or service is the offer on?", "hi": "ऑफ़र किस चीज़ या सर्विस पर है?", "kn": "ಆಫರ್ ಯಾವ ವಸ್ತು ಅಥವಾ ಸೇವೆಯ ಮೇಲೆ?"},
      "Say the item or service.",
      when=lambda f: not (_grow(f) and _v(f, "offer_type") == "no_offer")),
    Q("offer_type", "offer_type", "single", True,
      {"en": "What kind of offer is it?", "hi": "ऑफ़र किस तरह का है?", "kn": "ಆಫರ್ ಯಾವ ರೀತಿಯದು?"},
      "Percent off, a fixed price, buy one get one, a free item, or no offer.", when=lambda f: not _grow(f)),
    Q("discount_percent", "discount_percent", "number", True,
      {"en": "How many percent off?", "hi": "कितने प्रतिशत की छूट?", "kn": "ಎಷ್ಟು ಶೇಕಡಾ ರಿಯಾಯಿತಿ?"},
      "Say the percent as a number.", when=lambda f: _v(f, "offer_type") == "percent_off"),
    Q("price_amount", "price_amount", "number", True,
      {"en": "What is the offer price in rupees?", "hi": "ऑफ़र की कीमत कितने रुपये है?", "kn": "ಆಫರ್ ಬೆಲೆ ಎಷ್ಟು ರೂಪಾಯಿ?"},
      "Say the price in rupees.", when=lambda f: _v(f, "offer_type") == "fixed_price"),
    Q("start_date", "start_date", "date", True,
      {"en": "When does it start?", "hi": "यह कब से शुरू होगा?", "kn": "ಇದು ಯಾವಾಗ ಶುರುವಾಗುತ್ತದೆ?"},
      "Say a date or a weekday."),
    Q("end_date", "end_date", "date", False,
      {"en": "When does it end? You can skip.", "hi": "यह कब खत्म होगा? चाहें तो छोड़ दें।", "kn": "ಇದು ಯಾವಾಗ ಮುಗಿಯುತ್ತದೆ? ಬೇಕಿದ್ದರೆ ಬಿಡಿ."},
      "Say a date or a weekday, or skip."),
    Q("days", "days", "multi", True,
      {"en": "On which days is the offer valid?", "hi": "ऑफ़र किन दिनों में मान्य है?", "kn": "ಆಫರ್ ಯಾವ ದಿನಗಳಲ್ಲಿ ಇರುತ್ತದೆ?"},
      "Name the days, or say weekend, weekdays or every day."),
    Q("time_window", "time_window", "text", False,
      {"en": "What time of day? You can skip.", "hi": "दिन के किस समय? चाहें तो छोड़ दें।", "kn": "ದಿನದ ಯಾವ ಸಮಯ? ಬೇಕಿದ್ದರೆ ಬಿಡಿ."},
      "Say the hours, or skip."),
    Q("terms", "terms", "text", False,
      {"en": "Any conditions, like dine-in only? You can skip.", "hi": "कोई शर्त, जैसे सिर्फ़ डाइन-इन? चाहें तो छोड़ दें।", "kn": "ಯಾವುದಾದರೂ ಷರತ್ತು, ಉದಾ: ಡೈನ್-ಇನ್ ಮಾತ್ರ? ಬೇಕಿದ್ದರೆ ಬಿಡಿ."},
      "Say any condition, or skip."),
    Q("audiences", "audiences", "multi", True,
      {"en": "Who is this for?", "hi": "यह किनके लिए है?", "kn": "ಇದು ಯಾರಿಗಾಗಿ?"},
      "Pick any, or say your own."),
    Q("languages", "languages", "multi", True,
      {"en": "Which languages should the posts be in?", "hi": "पोस्ट किन भाषाओं में चाहिए?", "kn": "ಪೋಸ್ಟ್‌ಗಳು ಯಾವ ಭಾಷೆಗಳಲ್ಲಿ ಬೇಕು?"},
      "English, Kannada, Hindi."),
    Q("channels", "channels", "multi", True,
      {"en": "Where do you want to promote it?", "hi": "आप इसका प्रचार कहाँ करना चाहते हैं?", "kn": "ಇದನ್ನು ಎಲ್ಲಿ ಪ್ರಚಾರ ಮಾಡಬೇಕು?"},
      "Pick any number of channels."),
    Q("cta", "cta", "text", True,
      {"en": "What should customers do? Give a phone number, map link, website or Instagram handle.",
       "hi": "ग्राहक क्या करें? फ़ोन नंबर, मैप लिंक, वेबसाइट या इंस्टाग्राम हैंडल दीजिए।",
       "kn": "ಗ್ರಾಹಕರು ಏನು ಮಾಡಬೇಕು? ಫೋನ್ ನಂಬರ್, ಮ್ಯಾಪ್ ಲಿಂಕ್, ವೆಬ್‌ಸೈಟ್ ಅಥವಾ ಇನ್‌ಸ್ಟಾಗ್ರಾಮ್ ಹ್ಯಾಂಡಲ್ ಕೊಡಿ."},
      "Phone, link or @handle. Type it if easier.", when=lambda f: True),
    Q("email_recipients", "email_recipients", "list", False,
      {"en": "Who should get the email? Paste lines like Name <email>. You can skip.",
       "hi": "ईमेल किसे भेजना है? Name <email> जैसी लाइनें डालें। चाहें तो छोड़ दें।",
       "kn": "ಇಮೇಲ್ ಯಾರಿಗೆ ಕಳುಹಿಸಬೇಕು? Name <email> ಹೀಗೆ ಬರೆಯಿರಿ. ಬೇಕಿದ್ದರೆ ಬಿಡಿ."},
      "Type one person per line.", when=lambda f: "cold_email" in (_v(f, "channels") or [])),
    Q("tone", "tone", "single", True,
      {"en": "What tone suits your shop?", "hi": "आपकी दुकान के लिए कैसा टोन ठीक रहेगा?", "kn": "ನಿಮ್ಮ ಅಂಗಡಿಗೆ ಯಾವ ಧಾಟಿ ಸರಿ?"},
      "Pick one."),
)
BY_ID = {q.id: q for q in SCRIPT}

# ---------------------------------------------------------------- deterministic reading

WORDS: dict[str, dict[str, list[str]]] = {
    "business_type": {
        "cafe": ["cafe", "café", "coffee shop", "coffee", "chai", "ಕೆಫೆ", "कैफे", "कैफ़े"],
        "restaurant": ["restaurant", "hotel", "mess", "dhaba", "eatery", "canteen", "ರೆಸ್ಟೋರೆಂಟ್", "ಹೋಟೆಲ್", "रेस्टोरेंट", "होटल", "ढाबा"],
        "bakery": ["bakery", "bakes", "ಬೇಕರಿ", "बेकरी"],
        "salon": ["salon", "parlour", "parlor", "spa", "barber", "ಸಲೂನ್", "सैलून", "पार्लर"],
        "boutique": ["boutique", "clothing", "garments", "tailor", "ಬೂಟಿಕ್", "बुटीक"],
        "gym": ["gym", "fitness", "yoga", "ಜಿಮ್", "जिम"],
        "clinic": ["clinic", "dental", "doctor", "ಕ್ಲಿನಿಕ್", "क्लिनिक"],
        "coaching": ["coaching", "tuition", "institute", "academy", "ಕೋಚಿಂಗ್", "ಟ್ಯೂಷನ್", "कोचिंग"],
        "other": ["other"],
    },
    "goal": {
        "more_walkins": ["walk-in", "walkin", "walk in", "footfall", "more customers", "ಗ್ರಾಹಕ", "ग्राहक"],
        "promote_offer": ["promote", "offer", "discount", "sale", "ಆಫರ್", "ऑफ़र", "ऑफर"],
        "launch_product": ["launch", "new product", "new item", "new dish", "new menu", "लॉन्च"],
        "announce_opening": ["opening", "inaugur", "new shop", "new branch", "ಉದ್ಘಾಟನೆ", "उद्घाटन"],
        "grow_followers": ["follower", "followers", "grow", "ಫಾಲೋವರ್", "फॉलोअर"],
    },
    "offer_type": {
        "percent_off": ["percent", "%", "discount", "off", "ಶೇಕಡಾ", "ರಿಯಾಯಿತಿ", "प्रतिशत", "फीसदी", "छूट"],
        "fixed_price": ["rupees", "₹", "rs", "price", "fixed price", "ರೂಪಾಯಿ", "रुपये", "रुपए"],
        "buy_one_get_one": ["buy one get one", "buy 1 get 1", "bogo", "b1g1", "1+1", "one plus one", "ek ke saath ek",
                            "ek pe ek", "ondu ge ondu", "ondu tagondre ondu", "ondu tagondre", "एक के साथ एक", "ಒಂದಕ್ಕೆ ಒಂದು"],
        "free_item": ["free", "complimentary", "ಉಚಿತ", "मुफ़्त", "मुफ्त", "फ्री"],
        "no_offer": ["no offer", "no discount", "without offer", "just followers", "offer illa", "koi offer nahi", "ಆಫರ್ ಇಲ್ಲ", "ऑफ़र नहीं"],
    },
    "audiences": {
        "students": ["student", "college", "school", "ವಿದ್ಯಾರ್ಥಿ", "छात्र", "विद्यार्थी"],
        "office_workers": ["office", "professional", "employee", "techie", "corporate", "ಆಫೀಸ್", "ऑफिस"],
        "families": ["family", "families", "kids", "parents", "ಕುಟುಂಬ", "परिवार"],
        "regulars": ["regular", "loyal", "repeat", "ನಿಯಮಿತ", "नियमित"],
        "tourists": ["tourist", "ಪ್ರವಾಸಿ", "पर्यटक"],
        "nearby_residents": ["nearby", "neighbour", "neighbor", "resident", "locals", "around here", "ಸುತ್ತಮುತ್ತ", "आसपास"],
    },
    "languages": {
        "en": ["english", "angrezi", "ಇಂಗ್ಲಿಷ್", "अंग्रेज़ी", "अंग्रेजी"],
        "kn": ["kannada", "ಕನ್ನಡ", "कन्नड़", "कन्नड"],
        "hi": ["hindi", "ಹಿಂದಿ", "हिंदी", "हिन्दी"],
        **{code: names for code, names in languages.spoken_names().items() if code not in ("en", "kn", "hi")},
    },
    "channels": {
        "cold_email": ["email", "e-mail", "ಇಮೇಲ್", "ईमेल"],
        "instagram_story": ["story", "stories", "ಸ್ಟೋರಿ", "स्टोरी"],
        "blog_post": ["blog", "ಬ್ಲಾಗ್", "ब्लॉग"],
        "whatsapp": ["whatsapp", "whats app", "ವಾಟ್ಸಾಪ್", "व्हाट्सऐप", "व्हाट्सएप", "वॉट्सऐप"],
        "poster": ["poster", "banner", "ಪೋಸ್ಟರ್", "पोस्टर"],
        "google_business_post": ["google", "ಗೂಗಲ್", "गूगल"],
        "reel": ["reel", "video", "ರೀಲ್", "रील"],
    },
    "tone": {
        "friendly": ["friendly", "friend"],
        "warm_local": ["warm", "local", "homely", "traditional"],
        "playful": ["playful", "fun", "funny", "witty"],
        "straightforward": ["straight", "direct", "simple", "plain", "formal"],
    },
}
SKIP_WORDS = {"skip", "no", "none", "nothing", "n/a", "na"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"^\+?\d[\d\s-]{8,14}\d$")
URL_RE = re.compile(r"^(?:https?://|www\.)\S+$|^\S+\.(?:com|in|co|org|net|app|io)(?:/\S*)?$", re.IGNORECASE)


def has_word(segment: str, keyword: str) -> bool:
    if not keyword.isascii():
        return keyword in segment
    tail = r"(?![a-z0-9])" if len(keyword) <= 4 else ""
    return re.search(r"(?<![a-z0-9])" + re.escape(keyword) + tail, segment) is not None


def _matches(field_name: str, segment: str) -> list[str]:
    low = segment.lower()
    return [value for value, words in WORDS[field_name].items() if any(has_word(low, w) for w in words)]


@dataclass
class Reading:
    status: str  # accepted | ambiguous | rejected | none
    value: Any = None
    reason: str | None = None


def _accepted(value: Any, reason: str | None = None) -> Reading:
    return Reading("accepted", value, reason)


def _read_single(field_name: str, text: str) -> Reading:
    segs = speech.segments(text)
    for index in range(len(segs) - 1, -1, -1):
        found = _matches(field_name, segs[index])
        if field_name == "offer_type":
            if "no_offer" in found:
                found = ["no_offer"]
            if "buy_one_get_one" in found and "free_item" in found:
                found.remove("free_item")
        if len(found) > 1:
            return Reading("ambiguous", reason="I heard more than one: " + ", ".join(_label(v) for v in found) + ". Which one?")
        if found:
            dropped = [_matches(field_name, s) for s in segs[:index]]
            dropped = [x[0] for x in dropped if len(x) == 1]
            note = f"Took your last answer. Dropped: {', '.join(_label(d) for d in dropped)}." if dropped else None
            return _accepted(found[0], note)
    return Reading("none")


def _read_multi(field_name: str, text: str) -> Reading:
    low = text.lower()
    if field_name == "days":
        found = speech.read_days(text)
        return _accepted(found) if found else Reading("none")
    found = _matches(field_name, text)
    if field_name == "channels":
        if ("instagram" in low or "insta" in low) and "story" not in low and "stories" not in low:
            found.append("instagram_post")
        elif re.search(r"(instagram|insta|ig) post", low) and "instagram_post" not in found:
            found.append("instagram_post")
        found = [c for c in CHANNELS if c in found]
    if field_name == "languages":
        found = [lang for lang in LANGS if lang in found]
    if field_name == "audiences":
        customs = []
        for part in re.split(r",|;| and | & |\n", text):
            part = speech.squash(part)
            if part and not _matches("audiences", part) and len(part) <= 40:
                customs.append(part)
        found = [a for a in AUDIENCES if a in found] + customs
    return _accepted(found) if found else Reading("none")


def _read_number(field_name: str, text: str) -> Reading:
    marked = speech.percents if field_name == "discount_percent" else speech.rupees
    segs = speech.segments(text)
    for index in range(len(segs) - 1, -1, -1):
        seg = segs[index]
        values = sorted(set(marked(seg))) or sorted(set(speech.non_time_numbers(seg)))
        if len(values) > 1:
            return Reading("ambiguous", reason="I heard more than one number: " + ", ".join(f"{v:g}" for v in values) + ". Which one?")
        if values:
            value = values[0]
            earlier = [v for s in segs[:index] for v in (marked(s) or speech.numbers(s))]
            note = f"Took your last answer. Dropped: {', '.join(f'{v:g}' for v in earlier)}." if earlier else None
            return _range_check(field_name, value, note)
    return Reading("none")


def _range_check(field_name: str, value: float, note: str | None = None) -> Reading:
    if field_name == "discount_percent" and not 0 < value <= 100:
        return Reading("rejected", reason="A discount is between 1 and 100 percent.")
    if field_name == "price_amount" and value <= 0:
        return Reading("rejected", reason="A price must be above zero.")
    return _accepted(value, note)


def _read_date(text: str, today: date) -> Reading:
    read = speech.read_date(text, today)
    if read.status == "ok":
        return _accepted(read.iso)
    if read.status == "ambiguous":
        return Reading("ambiguous", reason=read.reason)
    return Reading("none")


def _read_cta(text: str) -> Reading:
    raw = speech.squash(text)
    digits = re.sub(r"[\s-]", "", speech.ascii_digits(raw))
    spoken = "".join(str(int(n)) for n in speech.numbers(raw) if n < 10 and float(n).is_integer())
    handle = re.fullmatch(r"@?([A-Za-z0-9_.]{2,30})", raw) if raw.startswith("@") else None
    if PHONE_RE.match(speech.ascii_digits(raw)) or (len(spoken) >= 10 and len(speech.numbers(raw)) == len(spoken)):
        number = digits.lstrip("+") if PHONE_RE.match(speech.ascii_digits(raw)) else spoken
        if raw.startswith("+"):
            number = "+" + number
        elif len(number) == 10:
            number = "+91" + number
        else:
            number = "+" + number if not number.startswith("+") else number
        return _accepted({"kind": "phone", "value": raw if PHONE_RE.match(speech.ascii_digits(raw)) else spoken,
                          "destination_url": "tel:" + number})
    if handle or "instagram.com" in raw.lower():
        name = handle.group(1) if handle else re.sub(r".*instagram\.com/", "", raw.lower()).strip("/").split("/")[0].split("?")[0]
        return _accepted({"kind": "instagram", "value": "@" + name, "destination_url": f"https://instagram.com/{name}"})
    if URL_RE.match(raw):
        url = raw if raw.lower().startswith("http") else "https://" + raw
        kind = "maps" if re.search(r"maps\.|goo\.gl/maps|google\.[a-z.]+/maps", url.lower()) else "url"
        return _accepted({"kind": kind, "value": raw, "destination_url": url})
    return Reading("rejected", reason="I need a phone number, a link or an Instagram handle.")


def _read_recipients(text: str) -> Reading:
    people = []
    bad = []
    for line in re.split(r"[\n;]+", text):
        line = line.strip()
        if not line:
            continue
        emails = EMAIL_RE.findall(line)
        if len(emails) != 1:
            bad.append(line)
            continue
        name = re.sub(r"[<>\"']", "", line.replace(emails[0], "")).strip(" ,-")
        people.append({"name": name, "email": emails[0]})
    if bad or not people:
        return Reading("rejected", reason="Each line needs exactly one email address." + (f" Check: {bad[0]}" if bad else ""))
    return _accepted(people)


def _read_text(field_name: str, text: str) -> Reading:
    cleaned = speech.squash(text)
    if not cleaned:
        return Reading("none")
    if field_name == "terms":
        cleaned = speech.squash(speech.words_to_digits(cleaned))
    if len(cleaned) > 200:
        return Reading("rejected", reason="Please keep it under 200 characters.")
    return _accepted(cleaned)


def read_deterministic(q: Q, text: str, today: date) -> Reading:
    f = q.field
    if q.kind == "single":
        return _read_single(f, text)
    if q.kind == "multi":
        return _read_multi(f, text)
    if q.kind == "number":
        return _read_number(f, text)
    if q.kind == "date":
        return _read_date(text, today)
    if f == "cta":
        return _read_cta(text)
    if q.kind == "list":
        return _read_recipients(text)
    return _read_text(f, text)


def read_choices(q: Q, choices: list[str]) -> Reading:
    """Taps map straight to option values. No AI, no parsing."""
    options = {o["value"] for o in OPTIONS.get(q.field, [])}
    if q.kind == "single":
        if len(choices) == 1 and choices[0] in options:
            return _accepted(choices[0])
        return Reading("rejected", reason="Pick one of the options.")
    if q.kind == "multi":
        custom_ok = q.field == "audiences"
        if choices and all(c in options or (custom_ok and 0 < len(c.strip()) <= 40) for c in choices):
            return _accepted([c.strip() if c not in options else c for c in choices])
        return Reading("rejected", reason="Pick from the options.")
    return Reading("rejected", reason="Type or say the answer.")


# ---------------------------------------------------------------- grounded AI fallback

def ai_messages(q: Q, text: str, today: date) -> list[dict[str, str]]:
    request = {
        "field": q.field,
        "question": q.prompt["en"],
        "kind": q.kind,
        "options": [o["value"] for o in OPTIONS.get(q.field, [])],
        "today": today.isoformat(),
        "owner_said": text,
    }
    return [
        {
            "role": "system",
            "content": (
                "You extract exactly one field from a small business owner's spoken or typed answer. "
                "Use only what the owner said. Never infer or compute a number, date or weekday they did not say. "
                "If the answer does not contain the field, status is null. If it could mean two things, status is ambiguous. "
                "For a self-correction such as 'no, I mean', take the last stated value. "
                "For kind single the value is one option value. For kind multi it is an array of option values; "
                "for audiences you may add the owner's own words as extra strings. "
                "For kind number it is a number. For kind date it is YYYY-MM-DD, only if the owner gave a day number or weekday. "
                "For kind text it is the shortest exact phrase from the owner's words that answers the question. "
                'Return only JSON: {"status": "value" | "null" | "ambiguous", "value": ..., "reason": "a few words"}.'
            ),
        },
        {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
    ]


def ground(q: Q, ai: dict[str, Any], text: str, today: date) -> Reading:
    """Accept the model's value only if the owner's own words contain it."""
    status = ai.get("status")
    if status == "ambiguous":
        return Reading("ambiguous", reason=str(ai.get("reason") or "I could not tell which you meant.")[:200])
    value = ai.get("value")
    if status != "value" or value in (None, "", []):
        return Reading("rejected", reason="I could not find that in what you said.")
    if q.kind == "single":
        return _accepted(value) if value in {o["value"] for o in OPTIONS.get(q.field, [])} else Reading("rejected", reason=f"'{value}' is not one of the options.")
    if q.kind == "multi":
        if not isinstance(value, list):
            return Reading("rejected", reason="I could not read the list.")
        options = {o["value"] for o in OPTIONS.get(q.field, [])}
        low = text.lower()
        for item in value:
            if item in options:
                continue
            if q.field == "audiences" and isinstance(item, str) and speech.squash(item).lower() in speech.squash(low):
                continue
            return Reading("rejected", reason=f"'{item}' is not in what you said.")
        if q.field == "days":
            heard = set(speech.read_days(text))
            if not set(value) <= heard:
                return Reading("rejected", reason="A day I could not hear in your words was suggested.")
        return _accepted(list(value))
    if q.kind == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            return Reading("rejected", reason="That was not a number.")
        if not speech.number_grounded(number, text):
            return Reading("rejected", reason=f"{number:g} was not in what you said.")
        return _range_check(q.field, number)
    if q.kind == "date":
        if not isinstance(value, str) or not speech.date_grounded(value, text, today):
            return Reading("rejected", reason=f"{value} was not a date you said.")
        if date.fromisoformat(value) < today:
            return Reading("rejected", reason=f"{value} has already passed.")
        return _accepted(value)
    if isinstance(value, str) and speech.squash(value).lower() in speech.squash(text).lower():
        return _read_text(q.field, value)
    return _read_text(q.field, text)


async def interpret(q: Q, text: str, choices: list[str], source: str, today: date, agnes: Any) -> Reading:
    """Taps first, then deterministic reading, then (with a key) the grounded extractor."""
    text = (text or "").strip()
    if choices:
        if choices == ["skip"] and not q.required:
            return _accepted(None, "Skipped.")
        return read_choices(q, choices)
    if not text:
        if not q.required:
            return _accepted(None, "Skipped.")
        return Reading("rejected", reason="Say or tap an answer.")
    if not q.required and speech.squash(text).lower() in SKIP_WORDS:
        return _accepted(None, "Skipped.")
    if q.field == "area":
        # A stated city/state is enough. Do not ask a model to demand an unstated locality.
        location = re.sub(r"^(?:it(?:'s| is)|(?:my |the )?(?:business|cafe|shop) is)\s+(?:located\s+)?in\s+", "", text, flags=re.I)
        return _read_text(q.field, location)
    spoken_text = q.kind == "text" and q.field != "cta" and source == "voice"
    reading = Reading("none") if spoken_text else read_deterministic(q, text, today)
    if reading.status == "none" and agnes is not None and q.field != "cta":
        try:
            raw = await agnes.chat(ai_messages(q, text, today), cache_kind="interview", temperature=0, max_tokens=400)
            return ground(q, parse_json_object(raw), text, today)
        except (AgnesError, ValueError, json.JSONDecodeError):
            pass
    if reading.status == "none":
        if spoken_text:
            return _read_text(q.field, text)
        return Reading("rejected", reason="I could not read that. Tap an option or type it.")
    return reading


# ---------------------------------------------------------------- session state

class AnswerIn(BaseModel):
    text: str | None = None
    choices: list[str] | None = None
    source: str = "typed"


class StartIn(BaseModel):
    lang: str = "en"


def _http(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _answers(db: Database, sid: str) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM interview_answer WHERE session_id = ? ORDER BY seq", (sid,))
    for row in rows:
        row["choices"] = json.loads(row["choices"])
        row["value"] = json.loads(row["value"]) if row["value"] is not None else None
    return rows


def walk(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], Q | None, int, int, list[dict[str, Any]]]:
    """Replay the script over the stored answers. Answers to questions a branch no longer reaches are ignored."""
    latest = {row["question_id"]: row for row in rows}
    fields: dict[str, dict[str, Any]] = {}
    nxt = None
    required = answered = 0
    shown: list[dict[str, Any]] = []
    for q in SCRIPT:
        if not q.when(fields):
            continue
        row = latest.get(q.id)
        if q.required:
            required += 1
        if row is not None:
            shown.append(row)
        if row is not None and row["status"] == "accepted":
            fields[q.field] = {"value": row["value"], "answer_id": row["id"]}
            if q.required:
                answered += 1
        elif nxt is None:
            nxt = q
    return fields, nxt, answered, required, shown


def _question_view(q: Q, lang: str) -> dict[str, Any]:
    return {
        "id": q.id, "field": q.field, "prompt": q.prompt.get(lang, q.prompt["en"]), "kind": q.kind,
        "options": OPTIONS.get(q.field, []), "required": q.required, "voice_hint": q.hint,
    }


def _answer_view(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row[k] for k in ("id", "question_id", "field", "raw_text", "choices", "source", "value", "status", "reason", "ts")}


def _session(db: Database, sid: str) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM interview_session WHERE id = ?", (sid,))
    if row is None:
        raise _http(404, "not_found", "No interview with that id.")
    fields, nxt, answered, required, shown = walk(_answers(db, sid))
    return {
        "id": sid,
        "lang": row["lang"],
        "status": "asking" if nxt else "complete",
        "question": _question_view(nxt, row["lang"]) if nxt else None,
        "clarify": json.loads(row["clarify"]) if row["clarify"] else None,
        "answers": [_answer_view(a) for a in shown],
        "fields": fields,
        "progress": {"answered": answered, "total_required": required},
    }


def _set_clarify(db: Database, sid: str, clarify: dict[str, Any] | None) -> None:
    db.execute("UPDATE interview_session SET clarify = ? WHERE id = ?",
               (json.dumps(clarify, ensure_ascii=False) if clarify else None, sid))


def _record(db: Database, sid: str, q: Q, body: AnswerIn, reading: Reading) -> None:
    seq = db.query_one("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM interview_answer WHERE session_id = ?", (sid,))["n"]
    db.execute(
        "INSERT INTO interview_answer (id, session_id, question_id, field, raw_text, choices, source, value, status, reason, ts, seq) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, sid, q.id, q.field, body.text or "", json.dumps(body.choices or []), body.source,
         json.dumps(reading.value, ensure_ascii=False) if reading.status == "accepted" else None,
         reading.status, reading.reason, now(), seq),
    )


def _agnes(request: Request) -> Any:
    return request.app.state.agnes if text_ready(request.app) else None


def _cross_check(q: Q, fields: dict[str, Any], reading: Reading) -> Reading:
    if q.field == "end_date" and reading.status == "accepted" and reading.value and _v(fields, "start_date"):
        if reading.value < _v(fields, "start_date"):
            return Reading("rejected", reason="The end date is before the start date.")
    return reading


@router.post("/interview/start")
def start(body: StartIn, request: Request) -> dict:
    if body.lang not in LANGS:
        raise _http(422, "bad_lang", "lang must be one of: " + ", ".join(LANGS) + ".")
    sid = uuid.uuid4().hex
    request.app.state.db.execute(
        "INSERT INTO interview_session (id, lang, campaign_id, clarify, created_at) VALUES (?, ?, NULL, NULL, ?)",
        (sid, body.lang, now()),
    )
    return _session(request.app.state.db, sid)


@router.get("/interview/{sid}")
def read_session(sid: str, request: Request) -> dict:
    return _session(request.app.state.db, sid)


@router.post("/interview/{sid}/answer")
async def answer(sid: str, body: AnswerIn, request: Request) -> dict:
    db = request.app.state.db
    session = _session(db, sid)
    if session["question"] is None:
        raise _http(409, "no_open_question", "Every question is answered. Finish, or edit an answer.")
    q = BY_ID[session["question"]["id"]]
    fields = {k: v for k, v in session["fields"].items()}
    reading = await interpret(q, body.text or "", body.choices or [], body.source, date.today(), _agnes(request))
    reading = _cross_check(q, fields, reading)
    _record(db, sid, q, body, reading)
    if reading.status == "accepted":
        _set_clarify(db, sid, None)
    else:
        _set_clarify(db, sid, {"field": q.field, "reason": reading.reason, "quote": body.text or ", ".join(body.choices or [])})
    return _session(db, sid)


@router.post("/interview/{sid}/answers/{aid}")
async def edit_answer(sid: str, aid: str, body: AnswerIn, request: Request) -> dict:
    db = request.app.state.db
    session = _session(db, sid)
    row = next((a for a in _answers(db, sid) if a["id"] == aid), None)
    if row is None:
        raise _http(404, "not_found", "No answer with that id in this interview.")
    q = BY_ID[row["question_id"]]
    fields = {k: v for k, v in session["fields"].items() if k != q.field}
    reading = await interpret(q, body.text or "", body.choices or [], body.source, date.today(), _agnes(request))
    reading = _cross_check(q, fields, reading)
    quote = body.text or ", ".join(body.choices or [])
    changed = reading.status == "accepted" and row["status"] == "accepted" and reading.value != row["value"]
    if changed and body.source == "voice" and q.kind in ("number", "date") and row["value"] is not None:
        # A spoken change to a number or date could be a mishearing, so the owner confirms it by typing or tapping.
        reading = Reading(
            "ambiguous",
            reason=f"I heard {reading.value:g}" if q.kind == "number" else f"I heard {reading.value}",
        )
        reading.reason += f" but you said {row['value']:g} earlier. Type or tap the one you want." if q.kind == "number" \
            else f" but you said {row['value']} earlier. Type or tap the one you want."
    if reading.status != "accepted":
        _set_clarify(db, sid, {"field": q.field, "reason": reading.reason, "quote": quote})
        return _session(db, sid)
    reason = reading.reason
    if changed:
        reason = f"Changed from {row['value']}." + (f" {reading.reason}" if reading.reason else "")
    db.execute(
        "UPDATE interview_answer SET raw_text = ?, choices = ?, source = ?, value = ?, status = 'accepted', reason = ?, ts = ? WHERE id = ?",
        (body.text or "", json.dumps(body.choices or []), body.source,
         json.dumps(reading.value, ensure_ascii=False) if reading.value is not None else None, reason, now(), aid),
    )
    _set_clarify(db, sid, None)
    return _session(db, sid)


def _required_missing(session: dict[str, Any]) -> list[str]:
    fields = session["fields"]
    return [q.field for q in SCRIPT if q.when(fields) and q.required and (fields.get(q.field) or {}).get("value") is None]


@router.post("/interview/{sid}/finish")
def finish(sid: str, request: Request) -> dict:
    db = request.app.state.db
    session = _session(db, sid)
    missing = _required_missing(session)
    if missing:
        raise _http(409, "interview_incomplete", "Still needed: " + ", ".join(dict.fromkeys(missing)) + ".")
    fields = session["fields"]
    try:
        facts, facts_sources = plan_module.facts_from_fields(fields)
    except ValueError as exc:
        raise _http(409, "facts_invalid", str(exc)) from exc
    answers = session["answers"]
    data = plan_module.build_data(fields, answers, facts_sources)
    service = Service(db)
    row = db.query_one("SELECT campaign_id FROM interview_session WHERE id = ?", (sid,))
    campaign_id = row["campaign_id"]
    try:
        if campaign_id is None:
            transcript = "\n".join(a["raw_text"] or ", ".join(a["choices"]) for a in answers if a["raw_text"] or a["choices"])
            campaign_id = service.create_campaign(transcript or "interview", _v(fields, "tone"))["id"]
            db.execute("UPDATE interview_session SET campaign_id = ? WHERE id = ?", (campaign_id, sid))
        elif db.facts_approved(campaign_id):
            raise _http(409, "plan_locked", "The plan is locked. Use change by voice to edit it.")
        service.save_facts(campaign_id, facts)
    except ServiceError as exc:
        raise _http(exc.status, exc.code, exc.message) from exc
    plan_module.store(db, campaign_id, data)
    return {"campaign_id": campaign_id}
