from cqa.domain import Conversation, Judgment, official_checklist
from cqa.source_checks import apply_source_checks
from test_backend import source


def test_informal_native_opening_does_not_pass_business_politeness():
    c=source(language='KZ');c['transcript'][3]['text']='Сәлем. Қай сайтқа кірдіңіз?'
    j=Judgment(criterion_id='empathy',value=True,rationale='Model passed.',evidence_turns=[4])
    changes=apply_source_checks(Conversation.model_validate(c),official_checklist().criteria,[j],{})
    assert j.value is False and changes[0]['before']['value'] is True


def test_success_thanks_is_not_evidence_of_lost_closure_opportunity():
    c=source(language='KZ');c['transcript'].append({'timestamp':'00:05','speaker':'client','text':'Ашылды, рақмет.'})
    c['transcript'][3]['text']='Сайтқа осы сілтеме арқылы кіресіз.'
    j=Judgment(criterion_id='closure',value=None,rationale='Model claims abrupt end.',evidence_turns=[5])
    audit={'closure':{'decision_facts':{'opportunity_lost':True,'operator_summary_or_help_offer_present':False,'operator_farewell_present':False}}}
    apply_source_checks(Conversation.model_validate(c),official_checklist().criteria,[j],audit)
    assert j.value is False


def test_actual_disconnection_is_not_overridden_by_thanks_check():
    c=source(language='KZ');c['transcript'] += [{'timestamp':'00:05','speaker':'client','text':'Ашылды, рақмет.'},{'timestamp':'00:06','speaker':'system','text':'Client disconnected.'}]
    j=Judgment(criterion_id='closure',value=None,rationale='Disconnected.',evidence_turns=[5])
    audit={'closure':{'decision_facts':{'operator_summary_or_help_offer_present':False,'operator_farewell_present':False}}}
    apply_source_checks(Conversation.model_validate(c),official_checklist().criteria,[j],audit)
    assert j.value is None


def test_good_closing_can_still_pass():
    c=source(language='EN');c['transcript'][3]['text']='Anything else I can help you with? Goodbye!'
    j=Judgment(criterion_id='closure',value=False,rationale='Wrong model grade.',evidence_turns=[4])
    apply_source_checks(Conversation.model_validate(c),official_checklist().criteria,[j],{})
    assert j.value is True
