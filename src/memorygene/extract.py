"""Deterministic rule-based extraction adapter prototype (research baseline).

This module is a narrow, rule-based adapter used only for reproducible offline
evaluation. The production path is the calling agent (an LLM) extracting
``Candidate`` fields from dialogue; here a fixed Chinese phrase table, a fixed
topic-normalisation map and a few regular expressions produce candidate fields.
It does **not** claim semantic understanding, generalisation, or
natural-language-understanding accuracy, and it is not a production parser.

Notes:

* Everything is deterministic: no clock reads, no randomness, no network, and
  no third-party dependencies.
* ``at`` is always supplied by the caller; this module never invents or rewrites
  evidence timestamps. ``expires_at`` is only filled when the utterance itself
  contains an explicit ISO date (``YYYY-MM-DD``); the fixed end-of-day
  ``T23:59:59Z`` convention is documented rather than inferred.
* ``source`` is a verbatim, whitespace-trimmed continuous substring of the input
  text (leading discourse fillers and trailing modal particles are trimmed).
* Only a fixed topic map is supported. Unmapped preferences are skipped with an
  explicit ``unmapped_topic`` reason instead of guessing a topic.
* Sensitive statements default to ``consent=False``. Consent is set only when
  the same text explicitly allows remembering; refusal text is skipped.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Fixed importance values used by the rule table.  The evaluation compares
# *bands* (low < 0.5 <= mid < 0.9 <= high), never exact scores.
HIGH_IMPORTANCE = 0.95
NORMAL_IMPORTANCE = 0.7
SENSITIVE_IMPORTANCE = 0.9
SKIP_IMPORTANCE = 0.1

_SENTENCE = re.compile(r"[^。！？!?；;\n]+")
_SEGMENT = re.compile(r"[^，,]+")

_CHANGE = (
    "现在最喜欢",
    "现在喜欢",
    "现在更喜欢",
    "现在更爱",
    "更喜欢",
    "更爱",
    "改成了",
    "改成",
    "改为",
    "换成了",
    "换成",
    "变成",
    "迷上了",
    "迷上",
    "开始喜欢",
    "现在住在",
    "现在搬到",
    "搬到",
    "搬去",
    "定居在",
)
_SUPPLEMENT = (
    "也挺喜欢",
    "也挺爱",
    "也挺",
    "也很喜欢",
    "也喜欢",
    "也爱",
    "也蛮喜欢",
    "也好看",
    "也不错",
    "也很好",
    "还挺",
    "有点喜欢",
    "还算喜欢",
)
_FAVORITE = ("最喜欢", "最爱", "偏爱", "中意", "喜欢", "爱")
_CORRECTION = ("说错了", "更正", "纠正", "搞错了")
_NEGATION = (
    "不再喜欢",
    "不再爱",
    "不喜欢",
    "不爱",
    "没兴趣",
    "戒了",
    "讨厌",
    "不要记住",
    "别记住",
    "不要保存",
    "别保存",
    "不用记住",
)
_HEDGE = (
    "可能",
    "好像",
    "也许",
    "大概",
    "估计",
    "不确定",
    "说不定",
    "应该是",
    "听说",
    "似乎",
)
_HIGH_CUES = ("请记住", "记住", "重要", "一定", "别忘", "纪念日", "生日")
_THIRD_PARTY = (
    "妈妈",
    "爸爸",
    "朋友",
    "同事",
    "同学",
    "妹妹",
    "姐姐",
    "哥哥",
    "弟弟",
    "老师",
    "家人",
    "女朋友",
    "男朋友",
    "对象",
    "爱人",
    "闺蜜",
    "室友",
    "孩子",
    "儿子",
    "女儿",
    "我妈",
    "我爸",
)
_CORRECTION_SPAN = re.compile(r"不是(?P<old>[^，,。！？]{1,10})[，,]?是(?P<new>[^，,。！？]{1,20})")
_CONSENT_ALLOW = re.compile(r"(?:可以|允许|同意)(?:记住|记下|保存|记录)")
_CONSENT_REFUSE = re.compile(r"(?:不要|别|不用)(?:记住|记下|保存|记录)")
_COMMAND_ONLY = re.compile(
    r"^(?:请|麻烦|你|帮我|帮我记住|你给我)*"
    r"(?:可以|允许|同意|要|能|不要|别|不用)?"
    r"(?:记住|记下|保存|记录|忘了|忘掉)"
    r"(?:这个|这些|下来|一下|吧|哦|吗|哈)*$"
)
_EXPIRY_PATTERNS = (
    re.compile(r"到(\d{4}-\d{2}-\d{2})"),
    re.compile(r"(\d{4}-\d{2}-\d{2})前有效"),
    re.compile(r"有效期(?:到|至)(\d{4}-\d{2}-\d{2})"),
)

_LEADING_FILLER = re.compile(
    r"^(?:嗯+|哦+|啊+|对了|其实|另外|还有|然后|而且|不过|但是|以及|"
    r"好吧|好的|那么|就是说|话说)[，,]?\s*"
)
_TRAILING_PARTICLE = re.compile(r"(?:了|吧|呢|啊|呀|啦|哈|嘛|哦|呗)+$")
_VALUE_LEADING_VERB = re.compile(r"^(?:的|了|喝|吃|穿|用|听|看|学|去|在|玩)")
_PRONOUN_TAIL = re.compile(r"(?:我|这个|那个|它|其实|最近|不过|就是|觉得|觉得挺)+$")
_INTENSIFIER_TAIL = re.compile(r"(?:挺|也|还|都|蛮|很|真)$")


@dataclass(frozen=True)
class TopicRule:
    """One fixed topic slot with its trigger words and value lexicon."""

    topic: str
    triggers: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    sensitive: bool = False
    capture: str | None = None


TOPIC_RULES = (
    TopicRule("profile.id_number", ("身份证",), sensitive=True, capture="id"),
    TopicRule(
        "profile.phone",
        ("手机号", "电话", "号码"),
        sensitive=True,
        capture="phone",
    ),
    TopicRule(
        "profile.address",
        ("地址", "门牌", "路", "街", "号楼", "号院"),
        sensitive=True,
        capture="address",
    ),
    TopicRule("profile.birthday", ("生日",), capture="date"),
    TopicRule("profile.anniversary", ("纪念日",), capture="date"),
    TopicRule(
        "preference.favorite_flower",
        ("花",),
        (
            "栀子花",
            "洋桔梗",
            "向日葵",
            "康乃馨",
            "郁金香",
            "玫瑰",
            "百合",
            "茉莉",
        ),
    ),
    TopicRule(
        "preference.favorite_drink",
        ("喝", "饮品", "饮料"),
        (
            "美式咖啡",
            "乌龙茶",
            "柠檬水",
            "绿茶",
            "奶茶",
            "咖啡",
            "果汁",
            "可乐",
            "茶",
        ),
    ),
    TopicRule(
        "preference.favorite_food",
        ("吃", "食物"),
        ("火锅", "拉面", "饺子", "寿司", "蛋糕", "披萨"),
    ),
    TopicRule(
        "preference.favorite_music",
        ("音乐", "歌"),
        ("古典乐", "摇滚乐", "民谣", "爵士乐", "钢琴曲"),
    ),
    TopicRule(
        "preference.favorite_color",
        ("颜色",),
        ("藏青色", "淡紫色", "蓝色", "红色", "绿色", "紫色", "黑色", "白色"),
    ),
    TopicRule(
        "preference.favorite_book",
        ("书", "小说"),
        ("科幻小说", "散文集", "推理小说"),
    ),
    TopicRule(
        "preference.favorite_movie",
        ("电影",),
        ("纪录片", "动画电影", "科幻电影"),
    ),
    TopicRule(
        "preference.favorite_sport",
        ("运动",),
        ("羽毛球", "游泳", "跑步", "瑜伽"),
    ),
    TopicRule(
        "preference.favorite_pet",
        ("宠物",),
        ("小猫", "小狗", "猫", "狗"),
    ),
    TopicRule(
        "profile.city",
        ("城市", "住在", "搬去", "定居"),
        ("虚构市", "样例市", "示范城"),
        capture="city",
    ),
)


@dataclass(frozen=True)
class Extraction:
    """Candidate fields plus provenance and the storage-layer decision."""

    namespace: str
    subject: str
    at: str
    topic: str = ""
    value: str = ""
    certainty: str = "explicit"
    intent: str = "assert"
    importance: float = NORMAL_IMPORTANCE
    scope: str = "persistent"
    session: str = ""
    sensitive: bool = False
    consent: bool = False
    expires_at: str | None = None
    source: str = ""
    decision: str = "write"
    skip_reason: str | None = None
    notes: str = field(default="")

    def candidate(self):
        """Build the core ``Candidate`` for a write extraction.

        Skipped extractions deliberately have no candidate, so a caller cannot
        accidentally persist evidence the rules decided to reject.
        """
        if self.decision != "write":
            raise ValueError("Skipped extraction has no Candidate")
        if not self.topic or not self.value or not self.source:
            raise ValueError("Write extraction requires topic, value and source")
        from .core import Candidate

        return Candidate(
            namespace=self.namespace,
            subject=self.subject,
            topic=self.topic,
            value=self.value,
            source=self.source,
            at=self.at,
            certainty=self.certainty,
            intent=self.intent,
            importance=self.importance,
            scope=self.scope,
            session=self.session,
            expires_at=self.expires_at,
            sensitive=self.sensitive,
            consent=self.consent,
        )


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("\u3000", " ").strip()


def _clean_value(raw: str) -> str:
    value = _norm(raw)
    value = value.strip("\"'“”‘’《》<>()（）[]【】")
    value = re.sub(r"^[的：:\s]+", "", value)
    value = _TRAILING_PARTICLE.sub("", value).strip()
    return value[:30]


def _source_of(raw: str) -> str:
    source = raw.strip()
    source = _LEADING_FILLER.sub("", source)
    source = _TRAILING_PARTICLE.sub("", source).strip()
    return source


def _lexicon_value(values: tuple[str, ...], text: str) -> str | None:
    best = None
    best_pos = -1
    for token in values:
        pos = text.rfind(token)
        if pos < 0:
            continue
        if best is None or len(token) > len(best) or (
            len(token) == len(best) and pos > best_pos
        ):
            best, best_pos = token, pos
    return best


def _detect_topic(text: str) -> tuple[TopicRule, str | None] | None:
    for rule in TOPIC_RULES:
        for trigger in rule.triggers:
            if trigger in text:
                return rule, trigger
    for rule in TOPIC_RULES:
        token = _lexicon_value(rule.values, text)
        if token is not None:
            return rule, token
    return None


def _capture_value(rule: TopicRule, segment: str) -> str:
    token = _lexicon_value(rule.values, segment)
    if token is not None:
        return token
    if rule.capture == "id":
        match = re.search(r"身份证(?:号)?(?:是|为)?[：:\s]*([0-9Xx]{15,18})", segment)
        return _clean_value(match.group(1)) if match else ""
    if rule.capture == "phone":
        match = re.search(
            r"(?:手机号|电话|号码)(?:是|为)?[：:\s]*([0-9][0-9\-\s]{5,}[0-9])",
            segment,
        )
        return _clean_value(match.group(1)) if match else ""
    if rule.capture == "address":
        match = re.search(
            r"(?:地址(?:是|为)?|住在|搬到|搬去|在)([^。！？，,；;]{2,30})", segment
        )
        return _clean_value(match.group(1)) if match else ""
    if rule.capture == "city":
        match = re.search(
            r"(?:住在|搬到|搬去|定居在?|城市是|城市)(?:了)?([^。！？，,；;]{2,20})",
            segment,
        )
        if match:
            return _clean_value(match.group(1))
        return ""
    if rule.capture == "date":
        match = re.search(
            r"(?:生日|纪念日)(?:是|为)?\s*"
            r"([0-9〇零一二三四五六七八九十百千\-年月日号]{2,20})",
            segment,
        )
        return _clean_value(match.group(1)) if match else ""
    markers = tuple(_CHANGE + _SUPPLEMENT + _FAVORITE)
    for marker in sorted(markers, key=len, reverse=True):
        index = segment.rfind(marker)
        if index < 0:
            continue
        rest = segment[index + len(marker) :]
        rest = _VALUE_LEADING_VERB.sub("", rest)
        value = _clean_value(rest)
        if value:
            return value
        if marker in _SUPPLEMENT:
            before = segment[:index]
            before = _PRONOUN_TAIL.sub("", before)
            before = _INTENSIFIER_TAIL.sub("", before)
            value = _clean_value(before)
            if value:
                return value
    return ""


def _intent(text: str) -> str:
    if any(marker in text for marker in _CORRECTION):
        return "correct"
    if any(marker in text for marker in _CHANGE):
        return "change"
    if any(marker in text for marker in _SUPPLEMENT):
        return "supplement"
    return "assert"


def _certainty(text: str) -> str:
    return "uncertain" if any(word in text for word in _HEDGE) else "explicit"


def _importance(text: str, sensitive: bool) -> float:
    if any(cue in text for cue in _HIGH_CUES):
        return HIGH_IMPORTANCE
    if sensitive:
        return SENSITIVE_IMPORTANCE
    return NORMAL_IMPORTANCE


def _expires_at(text: str) -> str | None:
    for pattern in _EXPIRY_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1) + "T23:59:59Z"
    return None


def _is_third_party(text: str) -> bool:
    return any(marker in text for marker in _THIRD_PARTY)


def _is_negated(text: str) -> bool:
    return any(marker in text for marker in _NEGATION)


def _has_memory_verb(text: str) -> bool:
    markers = _CHANGE + _SUPPLEMENT + _FAVORITE + _CORRECTION
    return any(marker in text for marker in markers) or "记住" in text


def _make(
    *,
    namespace: str,
    subject: str,
    at: str,
    scope: str,
    session: str,
    source: str,
    topic: str = "",
    value: str = "",
    certainty: str = "explicit",
    intent: str = "assert",
    importance: float = NORMAL_IMPORTANCE,
    sensitive: bool = False,
    consent: bool = False,
    expires_at: str | None = None,
    decision: str = "write",
    skip_reason: str | None = None,
    notes: str = "",
) -> Extraction:
    return Extraction(
        namespace=namespace,
        subject=subject,
        at=at,
        topic=topic,
        value=value,
        certainty=certainty,
        intent=intent,
        importance=importance,
        scope=scope,
        session=session,
        sensitive=sensitive,
        consent=consent,
        expires_at=expires_at,
        source=source,
        decision=decision,
        skip_reason=skip_reason,
        notes=notes,
    )


def _correction_extraction(
    sentence: str,
    *,
    namespace: str,
    subject: str,
    at: str,
    scope: str,
    session: str,
    expires_at: str | None,
) -> Extraction | None:
    if not any(marker in sentence for marker in _CORRECTION) and not re.search(
        r"不是[^，,。！？]{1,10}[，,]?是", sentence
    ):
        return None
    span = _CORRECTION_SPAN.search(sentence)
    if span:
        value = _clean_value(span.group("new"))
        topic_text = sentence
    else:
        value = ""
        topic_text = sentence
    detected = _detect_topic(topic_text)
    if detected is None:
        return None
    rule, _trigger = detected
    if not value:
        value = _lexicon_value(rule.values, sentence) or _capture_value(rule, sentence)
    if not value:
        return None
    return _make(
        namespace=namespace,
        subject=subject,
        at=at,
        scope=scope,
        session=session,
        source=_source_of(sentence),
        topic=rule.topic,
        value=value,
        certainty=_certainty(sentence),
        intent="correct",
        importance=_importance(sentence, rule.sensitive),
        sensitive=rule.sensitive,
        consent=bool(_CONSENT_ALLOW.search(sentence)),
        expires_at=expires_at,
        notes=f"rule=correction; topic_trigger={rule.topic}",
    )


def _skip(
    *,
    namespace: str,
    subject: str,
    at: str,
    scope: str,
    session: str,
    source: str,
    skip_reason: str,
    topic: str = "",
    value: str = "",
    importance: float = SKIP_IMPORTANCE,
    notes: str = "",
) -> Extraction:
    return _make(
        namespace=namespace,
        subject=subject,
        at=at,
        scope=scope,
        session=session,
        topic=topic,
        value=value,
        importance=importance,
        source=source,
        decision="skip",
        skip_reason=skip_reason,
        notes=notes,
    )


def _segment_extractions(
    sentence: str,
    *,
    namespace: str,
    subject: str,
    at: str,
    scope: str,
    session: str,
    expires_at: str | None,
    consent: bool,
    refusal: bool,
) -> list[Extraction]:
    out: list[Extraction] = []
    for match in _SEGMENT.finditer(sentence):
        segment = match.group()
        if not segment.strip():
            continue
        source = _source_of(segment)
        if not source:
            continue
        if _COMMAND_ONLY.match(_norm(source)):
            # "请记住" / "可以记住" / "不要记住" as a bare command carries no
            # memory content; consent/refusal is handled where it matters.
            continue
        if _is_third_party(segment):
            detected = _detect_topic(segment)
            rule = detected[0] if detected else None
            value = _capture_value(rule, segment) if rule else ""
            out.append(
                _skip(
                    namespace=namespace,
                    subject=subject,
                    at=at,
                    scope=scope,
                    session=session,
                    source=source,
                    skip_reason="third_party",
                    topic=rule.topic if rule else "",
                    value=value,
                    notes="third-person statement is not attributed to subject",
                )
            )
            continue
        if _is_negated(segment):
            detected = _detect_topic(segment)
            rule = detected[0] if detected else None
            value = _capture_value(rule, segment) if rule else ""
            out.append(
                _skip(
                    namespace=namespace,
                    subject=subject,
                    at=at,
                    scope=scope,
                    session=session,
                    source=source,
                    skip_reason="negation",
                    topic=rule.topic if rule else "",
                    value=value,
                    notes="core has no delete semantics; negation is not stored",
                )
            )
            continue
        if _CONSENT_REFUSE.search(segment) and "记住" in segment:
            # A bare refusal clause is only itself skipped; the sensitive
            # candidate it refuses is handled below.
            continue
        detected = _detect_topic(segment)
        if detected is None:
            if _has_memory_verb(segment):
                out.append(
                    _skip(
                        namespace=namespace,
                        subject=subject,
                        at=at,
                        scope=scope,
                        session=session,
                        source=source,
                        skip_reason="unmapped_topic",
                        notes="no fixed topic mapping; refusing to guess",
                    )
                )
            continue
        rule, trigger = detected
        value = _capture_value(rule, segment)
        if not value:
            out.append(
                _skip(
                    namespace=namespace,
                    subject=subject,
                    at=at,
                    scope=scope,
                    session=session,
                    source=source,
                    skip_reason="no_value",
                    topic=rule.topic,
                    notes="topic detected but no value string extracted",
                )
            )
            continue
        if rule.sensitive:
            if refusal:
                out.append(
                    _skip(
                        namespace=namespace,
                        subject=subject,
                        at=at,
                        scope=scope,
                        session=session,
                        source=source,
                        skip_reason="consent_refused",
                        topic=rule.topic,
                        value=value,
                        notes="explicit refusal to remember sensitive data",
                    )
                )
                continue
            out.append(
                _make(
                    namespace=namespace,
                    subject=subject,
                    at=at,
                    scope=scope,
                    session=session,
                    source=source,
                    topic=rule.topic,
                    value=value,
                    certainty=_certainty(segment),
                    intent=_intent(segment),
                    importance=_importance(segment, sensitive=True),
                    sensitive=True,
                    consent=consent,
                    expires_at=expires_at,
                    notes=f"rule=sensitive; trigger={trigger}; consent_from_text={consent}",
                )
            )
            continue
        intent = _intent(segment)
        out.append(
            _make(
                namespace=namespace,
                subject=subject,
                at=at,
                scope=scope,
                session=session,
                source=source,
                topic=rule.topic,
                value=value,
                certainty=_certainty(segment),
                intent=intent,
                importance=_importance(segment, sensitive=False),
                expires_at=expires_at,
                notes=f"rule=preference; intent={intent}; trigger={trigger}",
            )
        )
    return out


def extract(
    text: str,
    *,
    namespace: str,
    subject: str,
    at: str,
    session: str = "",
    source_span: str | None = None,
) -> list[Extraction]:
    """Extract candidate memory fields from one user utterance.

    Args:
        text: Raw user text. It is treated strictly as data; no instruction in
            it is executed.
        namespace: Logical memory namespace, supplied by the caller.
        subject: Memory subject, supplied by the caller. Third-person
            statements are never attributed to this subject.
        at: Evidence timestamp supplied by the caller (never inferred here).
        session: Optional session ID; when set, write extractions use
            ``scope="session"``.
        source_span: Optional verbatim sub-span of ``text`` to analyse. This
            lets a caller point at the relevant fragment without rewriting it.

    Returns:
        A list of :class:`Extraction` objects in text order. Items with
        ``decision="skip"`` carry a ``skip_reason`` and must not be ingested.
        If no memory-bearing statement is found, a single ``low_importance``
        skip item is returned.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be non-empty text")
    for name, value in (("namespace", namespace), ("subject", subject), ("at", at)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be non-empty text")
    if not isinstance(session, str):
        raise ValueError("session must be text")
    if source_span is not None:
        if not isinstance(source_span, str) or not source_span.strip():
            raise ValueError("source_span must be non-empty text")
        if source_span not in text:
            raise ValueError("source_span must be a verbatim substring of text")
        work = source_span
    else:
        work = text

    scope = "session" if session else "persistent"
    expires_at = _expires_at(work)
    consent = bool(_CONSENT_ALLOW.search(work))
    refusal = bool(_CONSENT_REFUSE.search(work))
    results: list[Extraction] = []

    for sentence_match in _SENTENCE.finditer(work):
        sentence = sentence_match.group()
        if not sentence.strip():
            continue
        correction = _correction_extraction(
            sentence,
            namespace=namespace,
            subject=subject,
            at=at,
            scope=scope,
            session=session,
            expires_at=expires_at,
        )
        if correction is not None:
            results.append(correction)
            continue
        results.extend(
            _segment_extractions(
                sentence,
                namespace=namespace,
                subject=subject,
                at=at,
                scope=scope,
                session=session,
                expires_at=expires_at,
                consent=consent,
                refusal=refusal,
            )
        )

    if not results:
        fallback_source = re.sub(
            r"[。！？!?；;，,\s]+$", "", _source_of(work)
        )[:60]
        return [
            _skip(
                namespace=namespace,
                subject=subject,
                at=at,
                scope=scope,
                session=session,
                source=fallback_source,
                skip_reason="low_importance",
                notes="no memory-bearing statement; small talk or irrelevant text",
            )
        ]
    return results
