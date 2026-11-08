from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

Value = StrictBool | StrictInt | None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Turn(StrictModel):
    timestamp: str
    speaker: Literal['client', 'operator', 'bot', 'system']
    text: str


class Conversation(StrictModel):
    conversation_id: str = Field(min_length=1, max_length=200)
    channel: Literal['agent chat', 'voice call']
    language: Literal['RU', 'KZ', 'EN']
    transcript: list[Turn] = Field(min_length=1)
    audio_url: str | None = None


class Criterion(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    section: str = ''
    weight: float = Field(ge=0, le=10000, allow_inf_nan=False)
    response_type: Literal['boolean', 'scale', 'flag']
    allowed_values: list[Value] = Field(min_length=1)
    allow_na: bool = False
    na_condition: str = ''

    @model_validator(mode='after')
    def check_definition(self):
        values = self.allowed_values
        if len({(type(v), v) for v in values}) != len(values):
            raise ValueError('Duplicate allowed values')
        if (None in values) != self.allow_na:
            raise ValueError('allowed_values must include null exactly when allow_na is true')
        if self.allow_na and not self.na_condition.strip():
            raise ValueError('N/A requires an explicit condition')
        present = [v for v in values if v is not None]
        if self.response_type == 'scale':
            if not present or any(type(v) is not int or v < 0 for v in present) or max(present) <= 0:
                raise ValueError('Scale requires nonnegative integer steps and a positive maximum')
        elif {(type(v), v) for v in present} != {(bool, True), (bool, False)}:
            raise ValueError('Boolean and flag criteria require true and false')
        if self.response_type == 'flag' and (self.weight != 0 or self.allow_na):
            raise ValueError('Flags have zero weight and cannot be N/A')
        return self


class ChecklistInput(StrictModel):
    name: str = Field(min_length=1)
    criteria: list[Criterion] = Field(min_length=1, max_length=30)

    @model_validator(mode='after')
    def check_criteria(self):
        if len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError('Criterion IDs must be unique')
        if not any(c.weight > 0 for c in self.criteria):
            raise ValueError('At least one positive weight is required')
        return self


class Judgment(StrictModel):
    criterion_id: str
    value: Value
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_turns: list[StrictInt] = Field(min_length=1)


class ModelOutput(StrictModel):
    criteria: list[Judgment]
    needs_review: StrictBool
    review_reason: str


def validate_judgments(criteria: list[Criterion], judgments: list[Judgment], turn_count: int):
    definitions = {c.id: c for c in criteria}
    ids = [j.criterion_id for j in judgments]
    if len(ids) != len(set(ids)) or set(ids) != set(definitions):
        raise ValueError('Each selected criterion must appear exactly once')
    for judgment in judgments:
        criterion = definitions[judgment.criterion_id]
        if not any(type(judgment.value) is type(v) and judgment.value == v for v in criterion.allowed_values):
            raise ValueError(f'Invalid value for {criterion.id}')
        if len(judgment.evidence_turns) != len(set(judgment.evidence_turns)):
            raise ValueError(f'Duplicate evidence turns for {criterion.id}')
        if any(t < 1 or t > turn_count for t in judgment.evidence_turns):
            raise ValueError(f'Evidence out of range for {criterion.id}')


def calculate_score(criteria: list[Criterion], judgments: list[Judgment]):
    by_id = {j.criterion_id: j for j in judgments}
    if len(by_id) != len(judgments) or set(by_id) != {c.id for c in criteria}:
        raise ValueError('Score requires one judgment per criterion')
    earned = Decimal(0)
    applicable = Decimal(0)
    contributions = []
    for criterion in criteria:
        value = by_id[criterion.id].value
        if not any(type(value) is type(v) and value == v for v in criterion.allowed_values):
            raise ValueError(f'Invalid scoring value for {criterion.id}')
        if criterion.response_type == 'flag' or value is None:
            contributions.append({'criterion_id': criterion.id, 'earned_before_normalization': None if value is None else 0})
            continue
        weight = Decimal(str(criterion.weight))
        fraction = Decimal(int(value)) if type(value) is bool else Decimal(value) / Decimal(max(v for v in criterion.allowed_values if type(v) is int))
        points = weight * fraction
        earned += points
        applicable += weight
        contributions.append({'criterion_id': criterion.id, 'earned_before_normalization': float(points)})
    final = float((100 * earned / applicable).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) if applicable else None
    critical = by_id.get('critical')
    return {'final_score': final, 'critical_flag': bool(critical and critical.value is True)}, contributions


def official_checklist():
    rows = [
        ('contact', 'Contact', 10, 'boolean', [True, False], '', 'The operator greets in the customer language AND introduces themself in their FIRST reply. Bot greetings do not count.'),
        ('discovery', 'Discovery', 15, 'boolean', [True, False, None], 'Enough information was available from the start.', 'Uses already-known details and clarifies missing information before answering; repeating an already-answered question does not count.'),
        ('identification', 'Identification', 20, 'boolean', [True, False, None], 'No identity verification was required for this request.', 'Identity verification is CONFIRMED before personal information is disclosed or a protected action is performed. Requesting OTP, receiving data, or app login alone is not confirmation. Required but unconfirmed means false.'),
        ('consultation', 'Correct and complete consultation', 20, 'scale', [0, 5, 10, 15, 20, None], 'Conversation ended before the customer formulated a request.', '20: all material requests answered or a correct next step. 15: main request answered, minor detail missed. 10: partial answer, material question unresolved. 5: generic hint without actionable clarity. 0: no substantive answer or key advice wrong. Track every customer request separately; do not invent corporate policies.'),
        ('empathy', 'Empathy', 15, 'boolean', [True, False], '', 'Polite throughout; if customer expresses dissatisfaction or inconvenience, acknowledges that specific problem.'),
        ('dialogue', 'Dialogue management', 15, 'scale', [0, 4, 7, 10], '', '10: clear coherent replies, warns about explicit waiting. 7: one notable lapse but understandable. 4: customer must ask again because wording/order is unclear. 0: incoherent/contradictory dialogue. Do not penalize the excluded 3-minute first-response SLA. Separate bad reception/ASR from operator clarity.'),
        ('closure', 'Closure', 5, 'boolean', [True, False, None], 'Conversation was interrupted before an opportunity to close.', 'Summarizes OR offers further assistance, AND says goodbye. Farewell alone does not satisfy the literal rule; flag ambiguity for human review.'),
        ('critical', 'Critical violations', 0, 'flag', [True, False], '', 'True only for insulting the customer, proposing private paid services bypassing the company, or disclosing confidential information. A private paid proposal is enough without customer agreement. Cite actual offending turn(s). General terseness is not automatically an insult.'),
    ]
    return ChecklistInput(name='Official checklist v1', criteria=[Criterion(id=i, title=t, weight=w, response_type=k, allowed_values=v, allow_na=None in v, na_condition=na, description=d) for i,t,w,k,v,na,d in rows])
