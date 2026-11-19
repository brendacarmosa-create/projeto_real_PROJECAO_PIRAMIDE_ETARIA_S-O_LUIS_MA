# dashboard_sao_luis.py - São Luís: Censo 2022 x projeção 2025
# Fontes: IBGE (Censo 2022, API SIDRA) e DATASUS (SIM e SINASC, 2022-2025)
# Rode: py dashboard_sao_luis.py
import re                           # acha números dentro de textos
import io                           # trata um texto como se fosse arquivo
import requests                     # chama a API do IBGE
import pandas as pd                 # DataFrame
import matplotlib.pyplot as plt     # gráficos

# ============ 1. DADOS DO DATASUS (colados do TabNet) ============
NASCIMENTOS = '''"Ano do nascimento";"Masc";"Fem";"Ign";"Total"
"2022";6963;6718;9;13690
"2023";6690;6247;1;12938
"2024";6223;5786;4;12013
"2025";6139;5806;5;11950
"Total";26015;24557;19;50591'''

OBITOS = '''"Faixa Etária";"Masc";"Fem";"Ign";"Total"
"Menor 1 ano";448;376;8;832
"1 a 4 anos";66;55;-;121
"5 a 9 anos";49;28;-;77
"10 a 14 anos";46;32;1;79
"15 a 19 anos";200;77;-;277
"20 a 29 anos";840;227;-;1067
"30 a 39 anos";933;375;-;1308
"40 a 49 anos";1254;728;-;1982
"50 a 59 anos";1665;1136;-;2801
"60 a 69 anos";2383;1790;-;4173
"70 a 79 anos";2698;2351;-;5049
"80 anos e mais";2958;4592;-;7550
"Idade ignorada";29;3;2;34
"Total";13569;11770;11;25350'''

nasc = pd.read_csv(io.StringIO(NASCIMENTOS), sep=';', na_values='-').fillna(0)
nasc = nasc[nasc['Ano do nascimento'].astype(str) != 'Total'].copy()
nasc['Ano do nascimento'] = nasc['Ano do nascimento'].astype(int)

obitos = pd.read_csv(io.StringIO(OBITOS), sep=';', na_values='-').fillna(0)
obitos = obitos[~obitos['Faixa Etária'].isin(['Total', 'Idade ignorada'])].copy()


def faixa_obito(texto):
    """Devolve (idade inicial, idade final) de cada faixa do DATASUS."""
    if texto.startswith('Menor'):
        return 0, 0
    if 'e mais' in texto:
        return 80, 100
    a, b = map(int, re.findall(r'\d+', texto))
    return a, b


obitos['ini'] = obitos['Faixa Etária'].apply(lambda t: faixa_obito(t)[0])
obitos['fim'] = obitos['Faixa Etária'].apply(lambda t: faixa_obito(t)[1])

# ============ 2. CENSO 2022 PELA API DO IBGE ============
url = ('https://apisidra.ibge.gov.br/values/t/9514/n6/2111300/v/93'
       '/p/all/c2/4,5/c287/all/c286/all')
dados = requests.get(url, timeout=60).json()
df = pd.DataFrame(dados[1:]).rename(columns=dados[0])


def coluna(trecho):
    """Acha a coluna cujo nome contém o trecho (ex.: 'Sexo')."""
    return [c for c in df.columns if trecho in c and 'Código' not in c][0]


col_sexo, col_idade, col_forma = coluna('Sexo'), coluna('Idade'), coluna('Forma')
df['pop'] = pd.to_numeric(df['Valor'], errors='coerce')
df = df[df[col_forma] == 'Total']
faixa5 = df[col_idade].str.match(r'^\d+ a \d+ anos$')
mais100 = df[col_idade].str.contains('100 anos ou mais')
df = df[faixa5 | mais100].copy()
df['inicio'] = df[col_idade].apply(lambda t: int(re.findall(r'\d+', t)[0]))
df = df[df['inicio'] % 5 == 0]

# Quebra cada faixa de 5 anos em idades simples (divide igualmente por 5)
pop1 = {}                                     # (sexo, idade) -> pessoas
for _, r in df.iterrows():
    s, ini = r[col_sexo], r['inicio']
    idades = [100] if ini >= 100 else range(ini, ini + 5)
    for a in idades:
        pop1[(s, a)] = pop1.get((s, a), 0) + r['pop'] / len(idades)

# ============ 3. TAXA ANUAL DE MORTALIDADE POR IDADE E SEXO ============
ANOS_OBITOS = 4                               # os óbitos somam 2022 a 2025
SEXOS = [('Homens', 'Masc'), ('Mulheres', 'Fem')]
taxa = {}
for _, r in obitos.iterrows():
    idades = range(r['ini'], r['fim'] + 1)
    for s, col in SEXOS:
        pop_faixa = sum(pop1.get((s, a), 0) for a in idades)
        m = (r[col] / ANOS_OBITOS) / pop_faixa if pop_faixa else 0
        for a in idades:
            taxa[(s, a)] = m

# ============ 4. PROJEÇÃO 2022 -> 2025 ============
ANOS_PROJ = 3
proj = {}
for (s, a), p in pop1.items():
    sobrevive = 1
    for k in range(ANOS_PROJ):                # aplica a mortalidade de cada ano vivido
        sobrevive *= 1 - taxa.get((s, min(a + k, 100)), 0)
    nova_idade = min(a + ANOS_PROJ, 100)
    proj[(s, nova_idade)] = proj.get((s, nova_idade), 0) + p * sobrevive

# Base da pirâmide: quem nasceu em 2023, 2024 e 2025 (descontando a mortalidade infantil)
for ano, idade in [(2023, 2), (2024, 1), (2025, 0)]:
    linha = nasc[nasc['Ano do nascimento'] == ano].iloc[0]
    for s, col in SEXOS:
        proj[(s, idade)] = proj.get((s, idade), 0) + linha[col] * (1 - taxa[(s, 0)])


# ============ 5. VOLTA PARA FAIXAS DE 5 ANOS ============
def para_5anos(pop):
    """Agrupa as idades simples de volta em faixas de 5 anos."""
    linhas = [(100 if a >= 100 else a // 5 * 5, s, p) for (s, a), p in pop.items()]
    t = (pd.DataFrame(linhas, columns=['inicio', 'sexo', 'pop'])
           .pivot_table(index='inicio', columns='sexo', values='pop', aggfunc='sum')
           .sort_index())
    t.index = [f'{i} a {i + 4} anos' if i < 100 else '100 anos ou mais' for i in t.index]
    return t


piram22, piram25 = para_5anos(pop1), para_5anos(proj)
total22, total25 = piram22.sum().sum(), piram25.sum().sum()
print(f'População 2022 (Censo): {total22:,.0f}'.replace(',', '.'))
print(f'População 2025 (projeção): {total25:,.0f}'.replace(',', '.'))
print(f'Variação: {(total25 / total22 - 1) * 100:.2f}%')

# ============ 6. DASHBOARD ============
AZUL, LARANJA = '#2F5D9E', '#D98C3F'
fig = plt.figure(figsize=(18, 13))
fig.suptitle('São Luís - Nascimentos, óbitos e pirâmide etária (2022 x projeção 2025)',
             fontsize=17, fontweight='bold')
grade = fig.add_gridspec(2, 2, height_ratios=[1, 1.7], hspace=0.3, wspace=0.3)

# --- Nascimentos por ano ---
ax = fig.add_subplot(grade[0, 0])
x = range(len(nasc))
b1 = ax.bar([i - 0.2 for i in x], nasc['Masc'], 0.4, color=AZUL, label='Homens')
b2 = ax.bar([i + 0.2 for i in x], nasc['Fem'], 0.4, color=LARANJA, label='Mulheres')
ax.bar_label(b1, fmt='%.0f', fontsize=8)
ax.bar_label(b2, fmt='%.0f', fontsize=8)
ax.set_xticks(list(x))
ax.set_xticklabels(nasc['Ano do nascimento'])
ax.set_ylim(0, nasc[['Masc', 'Fem']].max().max() * 1.15)
ax.set_title('Nascidos vivos por ano (SINASC)')
ax.legend()

# --- Óbitos por faixa etária (2022-2025) ---
ax = fig.add_subplot(grade[0, 1])
x = range(len(obitos))
b1 = ax.bar([i - 0.2 for i in x], obitos['Masc'], 0.4, color=AZUL, label='Homens')
b2 = ax.bar([i + 0.2 for i in x], obitos['Fem'], 0.4, color=LARANJA, label='Mulheres')
ax.set_xticks(list(x))
ax.set_xticklabels(obitos['Faixa Etária'], rotation=35, ha='right', fontsize=8)
ax.set_title('Óbitos por faixa etária - total 2022 a 2025 (SIM)')
ax.legend()


# --- Pirâmides lado a lado, com a mesma escala ---
def pct(t, total):
    """Homens negativos (barra para a esquerda) e mulheres positivas, em %."""
    return -t['Homens'] / total * 100, t['Mulheres'] / total * 100


h22, m22 = pct(piram22, total22)
h25, m25 = pct(piram25, total25)
limite = max(abs(h22).max(), m22.max(), abs(h25).max(), m25.max()) * 1.3

paineis = [(h22, m22, f'Censo 2022 | {total22:,.0f} hab.'),
           (h25, m25, f'Projeção 2025 | {total25:,.0f} hab.')]
for pos, (h, m, titulo) in enumerate(paineis):
    ax = fig.add_subplot(grade[1, pos])
    bh = ax.barh(h.index, h, color=AZUL, label='Homens')
    bm = ax.barh(m.index, m, color=LARANJA, label='Mulheres')
    ax.bar_label(bh, labels=[f'{abs(v):.1f}%' for v in h], padding=2, fontsize=7)
    ax.bar_label(bm, labels=[f'{v:.1f}%' for v in m], padding=2, fontsize=7)
    ax.set_xlim(-limite, limite)
    ax.axvline(0, color='black', lw=0.8)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f'{abs(v):.1f}%'))
    ax.set_title(titulo.replace(',', '.'))
    ax.legend(loc='upper right')

plt.savefig('dashboard_sao_luis.png', dpi=150, bbox_inches='tight')
plt.show()