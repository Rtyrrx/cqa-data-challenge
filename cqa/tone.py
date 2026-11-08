"""Conservative hints for model/human review, never lexical score penalties."""
import re

TONE_POLICY_VERSION = 'business-tone-v1'
_INFORMAL_ADDRESS = {
    'RU': re.compile(r'\b(?:ты|тебя|тебе|тобой|тобою|твой|твоя|твоё|твое|твои|твою|твоего|твоей|твоему|твоим|твоих)\b',re.I),
    'KZ': re.compile(r'\b(?:сен|сені|сенің|саған|сенімен|өзің|өзіңнің)\b',re.I),
}
_QUOTES = re.compile(r'«[^»]*»|“[^”]*”|"[^"\n]*"')


def tone_observations(conversation):
    pattern = _INFORMAL_ADDRESS.get(conversation.language)
    candidates = []
    held = False
    disconnected = False
    for index,turn in enumerate(conversation.transcript,1):
        if turn.speaker=='system':
            text=turn.text.casefold()
            if any(s in text for s in ('больше не находится на удержании','снят с удержания','resumed','off hold','no longer on hold')):
                held=False
            elif any(s in text for s in ('на удержании','on hold')):
                held=True
            if any(s in text for s in ('клиент завершил разговор','клиент завершил звонок','client disconnected','customer disconnected','call ended')):
                disconnected=True
            continue
        if pattern is None or turn.speaker!='operator' or held or disconnected:
            continue
        # Quoted pronouns, customer text and internal staff talk are not customer address.
        text = _QUOTES.sub(' ',turn.text)
        markers = sorted({m.group(0) for m in pattern.finditer(text)})
        if markers:
            candidates.append({'turn':index,'markers':markers})
    return {'policy_version':TONE_POLICY_VERSION,'possible_informal_address':candidates,
        'instruction':'Review actual customer address in context. These are candidates, not automatic violations. Absence of an explicit Вы/Сіз is not a failure. Lowercase вы/сіз is acceptable; English you is neutral.'}
