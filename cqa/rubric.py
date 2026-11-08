"""Versioned decision guidance for unchanged official criterion meanings."""
from .domain import official_checklist

RUBRIC_VERSION = 'evidence-rubric-v3-facts'
GUIDANCE = {
    'contact': 'Check only the FIRST human operator reply: suitable greeting in customer language AND self-introduction. Bot greeting does not count. Apply the team RU/KZ business-tone policy. Do not invent a name or penalize quoted foreign menu labels.',
    'discovery': 'First reconstruct what was already known when the operator joined, INCLUDING client/bot context. If all facts needed for the answer were already available, applicability=not_applicable (N/A), even if the operator redundantly asks again. If material facts were missing, applicable: true only when the operator asks a useful missing question before advising; false if they skip it, guess, or merely repeat known information. Explaining a solution is NOT a discovery question. Cite the earlier client facts and the actual operator question. Penalize unnecessary repetition separately under dialogue, not by inventing a successful discovery.',
    'identification': 'First decide whether the requested disclosure/action actually requires identity verification. General navigation/product information: not_applicable. Protected personalized data/action: applicable. Then true ONLY if completed verification is explicitly confirmed BEFORE the event; otherwise false. Requesting or receiving an OTP is not completed verification. Quote actual source evidence; do not assume app login proves it.',
    'consultation': 'List every material customer request mentally and check each answer/next step. 20=all material requests resolved or correct actionable next step; 15=main request resolved but minor detail missed; 10=material question remains; 5=generic hint without actionable clarity; 0=no substantive answer or key advice wrong. not_applicable ONLY when no customer request was formulated before the conversation ended. A concrete success confirmation supports that specific step; thanks/okay alone proves neither completeness nor factual correctness. Poor tone does NOT by itself reduce consultation. Without a company knowledge base do not invent tariffs/policies or assert unverified facts.',
    'empathy': 'Always applicable. Check BOTH respectful business tone across customer-facing replies AND acknowledgment of any expressed inconvenience/frustration. If no frustration, polite normal service is enough; do not demand an apology everywhere. If client explicitly objects to repeating information (I wrote above / Жоғарыда жаздым ғой), assess how the operator responds to that inconvenience, not just whether the technical answer is right. Under team policy an informal RU/KZ service greeting or familiar direct ты/сен address does not pass business politeness. Respectful Kazakh verb endings count; an explicit Сіз pronoun is not required. Quote the actual polite response or the segment of the missed acknowledgment. A final thanks cannot erase earlier behavior.',
    'dialogue': 'Always applicable. 10 requires no notable context/order/clarity lapse. Asking again for a fact already given and making the customer repeat it is a lapse even if the eventual answer works. 7=one notable lapse, then understandable progress. 4=repeated/serious wording or sequencing problems forcing clarification; 0=incoherent or contradictory flow. Distinguish client repeating known facts from asking a new follow-up, bad connection and ASR. Do not automatically choose 4 for one repeated question. Excluded first-response SLA does not reduce the grade. Explain why the selected step fits and cite the lapse if below 10.',
    'closure': 'First test whether there is POSITIVE source evidence that the opportunity to close was lost: explicit disconnection before closure was possible, client explicitly leaves/refuses further conversation, or stated truncation of the recording. A transcript simply ending is NOT evidence of interruption. Client says solved/thanks as the final turn: applicable, not automatic N/A. When applicable, true requires (summary OR offer of further help) AND farewell by the operator; otherwise false. Farewell alone is insufficient under the literal rubric. Cite the closing segment for omissions; never invent abrupt ending/disconnect. If genuinely uncertain, flag review rather than use N/A as a safe escape.',
    'critical': 'Always applicable, no score contribution. true ONLY for operator insult, private paid service bypassing company, or actual confidential information disclosure. Cite the actual offending operator phrase. No violation found=false; dry tone, redundant questions and poor closure are not automatically critical. A customer quote or internal hold discussion is not delivered operator abuse.',
}


def guidance_for(criterion):
    original = next((c for c in official_checklist().criteria if c.id==criterion.id),None)
    if (original and criterion.description==original.description
            and criterion.na_condition==original.na_condition
            and criterion.response_type==original.response_type
            and criterion.allowed_values==original.allowed_values):
        return GUIDANCE[criterion.id]
    return ''


def with_guidance(checklist):
    from .domain import Criterion
    return {**checklist,'evaluation_guidance_version':RUBRIC_VERSION,
        'evaluation_guidance':{c['id']:guidance_for(Criterion.model_validate(c)) for c in checklist['criteria']}}
