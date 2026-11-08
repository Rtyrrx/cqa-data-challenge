"""Narrow source checks for explicit policy violations and unsupported closure N/A."""
import copy
import re

from .contact import contact_observation
from .rubric import guidance_for

SOURCE_CHECK_VERSION='source-checks-v1'
_ACK=re.compile(r'^(?:ашылды|таптым|болды|получилось|наш[её]л[аи]?|спасибо|рақмет|рахмет|found it|it worked|thanks|thank you)(?:[\s,.!]*(?:рақмет|рахмет|спасибо|thanks|thank you))?[\s,.!]*$',re.I)
_DISCONNECT=re.compile(r'завершил|отключ|разрыв|оборвал|прерван|disconnect|connection lost|call ended|timed? out|timeout|үзіл|ажырат|truncat',re.I)
_BYE=re.compile(r'до свидания|до новых встреч|всего (?:доброго|хорошего)|хорошего (?:дня|вечера)|сау болыңыз|көріскенше|goodbye|\bbye\b|take care|have a (?:nice|good|great) (?:day|evening)',re.I)
_HELP=re.compile(r'anything else.*help|further (?:help|assistance)|ещ[её].*помочь|чем.*помочь|остались.*вопрос|тағы.*(?:көмек|сұрақ)|басқа.*сұрақ',re.I)


def apply_source_checks(conversation,criteria,judgments,audit):
    definitions={c.id:c for c in criteria}
    by_id={j.criterion_id:j for j in judgments}
    changes=[]

    def set_value(id,value,reason,turns):
        judgment=by_id[id]
        before=judgment.model_dump()
        prior=copy.deepcopy(audit.get(id,{}))
        judgment.value=value;judgment.rationale=reason;judgment.evidence_turns=turns
        audit[id]={'applicability':'applicable','applicability_reason':reason,'quote_turn':turns[0],
            'evidence_quote':conversation.transcript[turns[0]-1].text[:250],
            'decision_facts':prior.get('decision_facts',{}),'source_check':SOURCE_CHECK_VERSION}
        changes.append({'criterion_id':id,'before':before,'model_audit_before_check':prior,'after':judgment.model_dump()})

    opening=contact_observation(conversation)
    if 'empathy' in by_id and guidance_for(definitions['empathy']) and opening.get('informal_greeting'):
        set_value('empathy',False,
            f'The operator uses the informal service greeting “{opening["informal_greeting"]}” at turn {opening["turn"]}; this does not meet the team’s RU/KZ business-politeness policy. A useful solution is graded separately.',
            [opening['turn']])

    if 'closure' not in by_id or not guidance_for(definitions['closure']) or conversation.channel!='agent chat':
        return changes
    operator_turns=[(i,t) for i,t in enumerate(conversation.transcript,1) if t.speaker=='operator']
    if not operator_turns:return changes
    last_index,last=operator_turns[-1]
    if _BYE.search(last.text) and _HELP.search(last.text):
        set_value('closure',True,'The last operator reply explicitly offers further help AND says goodbye.',[last_index])
        audit['closure']['decision_facts'].update(opportunity_lost=False,
            operator_summary_or_help_offer_present=True,operator_farewell_present=True)
        return changes

    judgment=by_id['closure']
    cited=[conversation.transcript[i-1] for i in judgment.evidence_turns]
    facts=audit.get('closure',{}).get('decision_facts',{})
    if (judgment.value is None and cited
            and all(t.speaker=='client' and _ACK.fullmatch(t.text.strip()) for t in cited)
            and not any(t.speaker=='system' and _DISCONNECT.search(t.text) for t in conversation.transcript)
            and facts.get('operator_summary_or_help_offer_present') is False
            and facts.get('operator_farewell_present') is False):
        set_value('closure',False,
            'The cited final client message only confirms success/thanks; it does not prove an interrupted opportunity to close. The operator supplied neither a summary/help offer nor a farewell.',
            list(dict.fromkeys([last_index,*judgment.evidence_turns])))
        audit['closure']['decision_facts']['opportunity_lost']=False
    return changes
