# -*- coding: utf-8 -*-
"""
atualizar_placar.py — actualiza o Placar (placar-liga-portugal.html) na sua máquina.

Fonte: football-data.co.uk (ficheiro POR.csv, gratuito, sem chave, actualizado
cerca de duas vezes por semana; inclui todas as épocas e a corrente).

O script lê o CSV, filtra a época 2026/27, e escreve os resultados novos
directamente dentro do HTML (no bloco de dados embebido). Não precisa de
servidor: o dashboard continua a abrir com duplo clique.

Uso:
    python atualizar_placar.py CAMINHO/placar-liga-portugal.html
    python atualizar_placar.py CAMINHO/placar-liga-portugal.html --benfica       (também o detalhe FBref do Benfica)
    python atualizar_placar.py CAMINHO/placar-liga-portugal.html --csv POR.csv   (usar um CSV já descarregado)

A fase --benfica raspa o FBref com boas maneiras (1 pedido a cada 4 s, máx. 5
jogos novos por corrida) e escreve onzes, minutos e golos por jogador na linha
FOCO_EXTRA do HTML. Se o FBref mudar o formato, esta fase falha com aviso e a
dos resultados continua a funcionar.

Requisitos: Python 3.9+ — mais nada; usa apenas a biblioteca padrão.
Agendar: Task Scheduler (Windows) ou cron, 2x por semana chega.
"""
import sys, re, json, csv, io, datetime, urllib.request

URL_CSV = "https://www.football-data.co.uk/new/POR.csv"
EPOCA = 2026            # época 2026/27
BASE = datetime.date(2019, 1, 1)

# nomes football-data -> nomes do dashboard (openfootball)
ALIAS = {
    "benfica": "Benfica", "porto": "FC Porto", "sp lisbon": "Sporting CP",
    "sporting": "Sporting CP", "sp braga": "SC Braga", "braga": "SC Braga",
    "guimaraes": "Vitória SC", "vitoria guimaraes": "Vitória SC",
    "estoril": "Estoril Praia", "famalicao": "Famalicão", "gil vicente": "Gil Vicente",
    "casa pia": "Casa Pia", "rio ave": "Rio Ave", "arouca": "Arouca",
    "estrela": "Estrela da Amadora", "estrela amadora": "Estrela da Amadora",
    "santa clara": "Santa Clara", "nacional": "Nacional", "maritimo": "Marítimo",
    "moreirense": "Moreirense", "alverca": "Alverca",
    "ac viseu": "Académico de Viseu", "academico viseu": "Académico de Viseu",
    "academico de viseu": "Académico de Viseu", "viseu": "Académico de Viseu",
}

def limpa(n):
    n = n.strip().lower().replace(".", "").replace("-", " ")
    return re.sub(r"\s+", " ", n)

def canonico(nome, equipas):
    c = ALIAS.get(limpa(nome))
    if c and c in equipas:
        return c
    for e in equipas:  # último recurso: primeira palavra coincide
        if limpa(e).split()[0] == limpa(nome).split()[0]:
            return e
    return None

def descarrega(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")

def data_do_csv(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


# ---------------- fase 2: detalhe do Benfica via FBref ----------------
import time, html as _html

FBREF_EQUIPA = "https://fbref.com/en/squads/a2d435b3/Benfica-Stats"
PAUSA = 4.0          # segundos entre pedidos — boas maneiras
MAX_JOGOS_RUN = 5    # tecto de páginas de jogo por corrida

def fb_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (script pessoal de acompanhamento do Benfica; 1 pedido/4s)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")

def fb_destapar(pagina):
    # o FBref embrulha tabelas em comentários HTML; destapamos tudo
    return pagina.replace("<!--", "").replace("-->", "")

def fb_celulas(linha_html):
    out = {}
    for m in re.finditer(r'data-stat="([^"]+)"[^>]*>(.*?)</t[dh]>', linha_html, re.S):
        txt = re.sub(r"<[^>]+>", "", m.group(2))
        out[m.group(1)] = _html.unescape(txt).strip()
    return out

def fb_jogos_benfica():
    pag = fb_destapar(fb_get(FBREF_EQUIPA))
    m = re.search(r'<table[^>]*id="matchlogs_for"(.*?)</table>', pag, re.S)
    if not m:
        raise RuntimeError("tabela de jogos (matchlogs_for) não encontrada — formato mudou?")
    jogos = []
    for lm in re.finditer(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S):
        c = fb_celulas(lm.group(1))
        if not c.get("date") or not c.get("opponent"):
            continue
        rel = re.search(r'data-stat="match_report"[^>]*>.*?href="([^"]+)"', lm.group(1), re.S)
        jogos.append({
            "data": c.get("date", ""), "comp": c.get("comp", ""),
            "casa_fora": "casa" if c.get("venue", "").startswith("Home") else "fora",
            "adversario": c.get("opponent", ""), "gm": c.get("goals_for", ""),
            "gs": c.get("goals_against", ""),
            "rel": ("https://fbref.com" + rel.group(1)) if rel else None})
    return jogos

def fb_detalhe_jogo(url):
    pag = fb_destapar(fb_get(url))
    m = re.search(r'<table[^>]*id="stats_a2d435b3_summary"(.*?)</table>', pag, re.S)
    if not m:
        raise RuntimeError("tabela de jogadores não encontrada em " + url)
    jogadores = []
    for lm in re.finditer(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S):
        c = fb_celulas(lm.group(1))
        if not c.get("player") or c.get("player") in ("Player",):
            continue
        try:
            mins = int(c.get("minutes", "0") or 0)
        except ValueError:
            mins = 0
        try:
            gols = int(c.get("goals", "0") or 0)
        except ValueError:
            gols = 0
        jogadores.append({"nome": c["player"], "min": mins, "g": gols})
    # o FBref lista primeiro o onze inicial, depois os suplentes
    onze = [j["nome"] for j in jogadores[:11]]
    supl = [j["nome"] for j in jogadores[11:] if j["min"] > 0]
    return onze, supl, jogadores

COMP_PT = {"Primeira Liga": "Liga", "Liga Portugal": "Liga",
           "Europa Lg": "Liga Europa", "Champions Lg": "Liga dos Campeões",
           "Taça de Portugal": "Taça", "Taca de Portugal": "Taça"}

def fase_benfica(html_texto):
    m = re.search(r"const FOCO_EXTRA = (\[.*?\]); //", html_texto)
    if not m:
        raise RuntimeError("linha FOCO_EXTRA não encontrada no HTML — versão antiga do dashboard?")
    extra = json.loads(m.group(1))
    ja = {(e["jogo"][0].split(" ")[0].lower(), e["jogo"][2]) for e in extra}

    jogos = fb_jogos_benfica()
    novos, erros = 0, []
    for j in jogos:
        if not j["rel"] or j["gm"] == "" or novos >= MAX_JOGOS_RUN:
            continue
        res = "%s-%s" % (j["gm"], j["gs"]) if j["casa_fora"] == "casa" else "%s-%s" % (j["gs"], j["gm"])
        res_marcador = "%s-%s" % ((j["gm"], j["gs"]) if j["casa_fora"] == "casa" else (j["gs"], j["gm"]))
        chave = (j["adversario"].split(" ")[0].lower(), res_marcador)
        if chave in ja:
            continue
        time.sleep(PAUSA)
        try:
            onze, supl, jogadores = fb_detalhe_jogo(j["rel"])
        except RuntimeError as e:
            erros.append(str(e)); continue
        extra.append({
            "jogo": [j["adversario"], j["casa_fora"], res_marcador,
                     COMP_PT.get(j["comp"], j["comp"] or "Liga")],
            "onze": onze, "suplentes_usados": supl, "jogadores": jogadores})
        ja.add(chave); novos += 1

    if novos:
        html_texto = re.sub(r"const FOCO_EXTRA = \[.*?\]; //",
                            "const FOCO_EXTRA = " + json.dumps(extra, ensure_ascii=False) + "; //",
                            html_texto, count=1)
    return html_texto, novos, erros

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    caminho_html = sys.argv[1]
    csv_local = None
    if "--csv" in sys.argv:
        csv_local = sys.argv[sys.argv.index("--csv") + 1]

    html = open(caminho_html, encoding="utf-8").read()
    m = re.search(r"const OF_EMBED = (\{.*?\});\n", html, re.S)
    if not m:
        sys.exit("ERRO: bloco OF_EMBED não encontrado no HTML — é o ficheiro certo?")
    embed = json.loads(m.group(1))
    equipas = embed["equipas"]
    idx = {e: i for i, e in enumerate(equipas)}

    bruto = open(csv_local, encoding="utf-8", errors="replace").read() if csv_local else descarrega(URL_CSV)
    linhas = list(csv.DictReader(io.StringIO(bruto)))
    # o ficheiro "new/POR.csv" traz todas as épocas; a coluna Season é "2026/2027"
    alvo = [l for l in linhas if str(l.get("Season", "")).startswith(str(EPOCA))]
    if not alvo:
        sys.exit("ERRO: o CSV ainda não tem a época %d/%d." % (EPOCA, EPOCA + 1 - 2000))

    aplicados, ja_tinha, sem_par, avisos = 0, 0, 0, []
    pendentes = [l for l in embed["jogos"] if l[0] == 7 and l[5] < 0]
    for r in alvo:
        casa = canonico(r.get("Home", ""), equipas)
        fora = canonico(r.get("Away", ""), equipas)
        try:
            gc, gf = int(float(r["HG"])), int(float(r["AG"]))
        except (KeyError, ValueError, TypeError):
            continue  # jogo ainda sem resultado no CSV
        if not casa or not fora:
            sem_par += 1
            avisos.append("equipa não reconhecida: %s - %s" % (r.get("Home"), r.get("Away")))
            continue
        alvo_j = next((l for l in embed["jogos"]
                       if l[0] == 7 and l[3] == idx[casa] and l[4] == idx[fora]), None)
        if alvo_j is None:
            sem_par += 1
            avisos.append("par sem jogo no calendário: %s - %s" % (casa, fora))
            continue
        if alvo_j[5] >= 0:
            if (alvo_j[5], alvo_j[6]) != (gc, gf):
                avisos.append("DIVERGÊNCIA %s %d-%d (dashboard) vs %d-%d (CSV) — manteve-se o dashboard"
                              % (casa + "-" + fora, alvo_j[5], alvo_j[6], gc, gf))
            ja_tinha += 1
            continue
        d = data_do_csv(r.get("Date", ""))
        if d:
            alvo_j[2] = (d - BASE).days
        alvo_j[5], alvo_j[6] = gc, gf
        aplicados += 1

    if aplicados:
        novo = "const OF_EMBED = " + json.dumps(embed, ensure_ascii=False, separators=(",", ":")) + ";\n"
        html = re.sub(r"const OF_EMBED = \{.*?\};\n", lambda _: novo, html, count=1, flags=re.S)
        open(caminho_html, "w", encoding="utf-8").write(html)

    print("Época %d/%d — resultados novos aplicados: %d · já existentes: %d · sem correspondência: %d"
          % (EPOCA, EPOCA + 1 - 2000, aplicados, ja_tinha, sem_par))
    for a in avisos[:10]:
        print("  aviso:", a)
    if aplicados:
        print("HTML actualizado:", caminho_html)
    else:
        print("Nada para escrever — o dashboard já estava em dia com o CSV.")

    if "--benfica" in sys.argv:
        print("FBref: a procurar jogos do Benfica sem detalhe (1 pedido/4 s)…")
        try:
            html2 = open(caminho_html, encoding="utf-8").read()
            html2, novos, erros = fase_benfica(html2)
            if novos:
                open(caminho_html, "w", encoding="utf-8").write(html2)
            print("FBref: %d jogos detalhados nesta corrida." % novos)
            for e in erros[:5]:
                print("  aviso FBref:", e)
        except Exception as e:
            print("FBref falhou (a fase de resultados não foi afectada):", e)

if __name__ == "__main__":
    main()
