"""Публикационные тексты: только сведения выбранного произведения."""


def captions(selected):
    work, composer = selected['work'], selected['composer']
    ensemble, conductor = selected['ensemble'], selected['conductor']
    return f'''## YouTube — заголовок

{composer} — {work} | Արխիվային ձայնագրություն · Archive recording

## YouTube — описание

«{work}»
Կոմպոզիտոր՝ {composer}
Կատարող՝ {ensemble}
Դիրիժոր՝ {conductor}
Ամբողջական ձայնագրություն՝ առանց կրճատման։
Ձայնի վերականգնում և բարձրության նորմալացում չեն կիրառվել։

{work}
Composer: {composer}
Performed by: {ensemble}
Conductor: {conductor}
Complete recording, without cuts.
No audio restoration or loudness normalization applied.

#AlexandreSpendiarian #Hidjaz #ArmenianMusic #Սպենդիարյան #ՀայկականԵրաժշտություն

## Instagram — пост / карусель

«{work}» — {composer}
Կատարող՝ {ensemble}։ Դիրիժոր՝ {conductor}։

{work} — {composer}
Performed by {ensemble}. Conducted by {conductor}.

#AlexandreSpendiarian #Hidjaz #ArmenianMusic #Սպենդիարյան #ՀայկականԵրաժշտություն

## Instagram Reels — подпись

Հատված «{work}» ստեղծագործությունից։
Կոմպոզիտոր՝ {composer}։
Կատարող՝ {ensemble} · Դիրիժոր՝ {conductor}։

An excerpt from {work}.
Composer: {composer}.
{ensemble} · Conductor: {conductor}.

#AlexandreSpendiarian #Hidjaz #ArmenianMusic #Սպենդիարյան #ՀայկականԵրաժշտություն

## Instagram Story — текст

«{work}» · {composer}
Հատված ձայնագրությունից · Recording excerpt
'''
