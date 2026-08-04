# -*- coding: utf-8 -*-
"""Patch v3: novas telas (Analytics, Experiencia, Inovacao, Recrutamento) + menu + PostgreSQL"""
import os
path = r'C:\ecossistema-rh\app.py'

with open(path, 'r', encoding='utf-8') as f:
    code = f.read()

if '/analytics' in code:
    print('⚠️ Patch v3 já aplicado anteriormente.')
else:
    # ========== 1. SUPORTE A POSTGRESQL (Render) ==========
    old_db = "app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'ecossistema_rh.db')"
    new_db = "app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(BASE_DIR, 'ecossistema_rh.db'))"
    if old_db in code:
        code = code.replace(old_db, new_db)
        print('✅ PostgreSQL habilitado via DATABASE_URL (SQLite continua como fallback)')
    else:
        print('⚠️ Linha do banco não encontrada — verifique se já foi alterada')

    # ========== 2. NOVAS PÁGINAS (inseridas antes da API JSON) ==========
    marcador = '# ============ API JSON ============'
    novas_paginas = '''
# ============ RECRUTAMENTO INTELIGENTE ============
@app.route('/recrutamento')
def recrutamento():
    total_vagas = Vaga.query.count()
    total_candidaturas = Candidatura.query.count()
    total_candidatos = Usuario.query.filter_by(tipo='candidato').count()
    html = '<h1>Recrutamento Inteligente <span>// IA + Automação</span></h1><p class="sub">Matching preditivo, triagem NLP e agentes autônomos trabalhando 24/7</p><div class="painel"><h4>Indicadores ao Vivo</h4><div class="status">'
    html += '<div class="item"><span class="dot ciano"></span> Vagas ativas: <b>' + str(total_vagas) + '</b></div>'
    html += '<div class="item"><span class="dot"></span> Candidaturas: <b>' + str(total_candidaturas) + '</b></div>'
    html += '<div class="item"><span class="dot roxo"></span> Candidatos: <b>' + str(total_candidatos) + '</b></div>'
    html += '</div></div><div class="grade">'
    mods = [
        ('🧠','Matching Preditivo','IA compara skills, experiência e fit cultural para ranquear os melhores talentos.','#3b82f6'),
        ('🔍','Triagem com NLP','Processa currículos, extrai skills implícitas e detecta viés automaticamente.','#10b981'),
        ('✍️','Geração de Descrições','IA escreve descrições de vaga otimizadas para SEO e inclusão.','#f59e0b'),
        ('🤖','Agente Sourcing','Busca candidatos em múltiplas fontes 24/7 assim que a vaga é publicada.','#a855f7'),
        ('📅','Agente Scheduling','Negocia horários de entrevista automaticamente via chat.','#22d3ee'),
        ('📩','Agente Follow-up','Mantém cada candidato informado durante todo o processo.','#ef4444'),
    ]
    for icone, titulo, desc, cor in mods:
        html += '<div class="card" style="cursor:default"><div class="icone" style="background:' + cor + '22">' + icone + '</div><h3>' + titulo + '</h3><p>' + desc + '</p><p style="margin-top:8px"><span class="pill aberta">● Ativo</span></p></div>'
    html += '</div>'
    return pagina(html, 'recrut')

# ============ ANALYTICS ============
@app.route('/analytics')
def analytics():
    total_vagas = Vaga.query.count()
    total_candidaturas = Candidatura.query.count()
    total_candidatos = Usuario.query.filter_by(tipo='candidato').count()
    total_empresas = Usuario.query.filter_by(tipo='empresa').count()
    scores = [c.match_score or 0 for c in Candidatura.query.all()]
    score_medio = round(sum(scores) / len(scores), 1) if scores else 0
    html = '<h1>Analytics <span>// People Analytics</span></h1><p class="sub">Indicadores em tempo real do ecossistema</p><div class="painel"><h4>KPIs Principais</h4><div class="status">'
    html += '<div class="item"><span class="dot ciano"></span> Vagas: <b>' + str(total_vagas) + '</b></div>'
    html += '<div class="item"><span class="dot"></span> Candidaturas: <b>' + str(total_candidaturas) + '</b></div>'
    html += '<div class="item"><span class="dot roxo"></span> Candidatos: <b>' + str(total_candidatos) + '</b></div>'
    html += '<div class="item"><span class="dot ambar"></span> Empresas: <b>' + str(total_empresas) + '</b></div>'
    html += '<div class="item"><span class="dot roxo"></span> Match Score Médio: <b>' + str(score_medio) + '%</b></div>'
    html += '</div></div>'
    por_nivel = {}
    for v in Vaga.query.all():
        cod = v.nivel_codigo or 'Geral'
        por_nivel[cod] = por_nivel.get(cod, 0) + 1
    itens = sorted(por_nivel.items(), key=lambda x: x[1], reverse=True)[:8]
    max_v = max([c for _, c in itens], default=1) or 1
    html += '<div class="painel"><h4>Vagas por Nível</h4>'
    for cod, qtd in itens:
        pct = int(qtd / max_v * 100)
        html += '<div style="margin-bottom:10px"><div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px"><span>' + cod + '</span><span><b>' + str(qtd) + '</b></span></div><div class="barra"><span style="width:' + str(pct) + '%"></span></div></div>'
    html += '</div>'
    ultimas = Candidatura.query.order_by(Candidatura.id.desc()).limit(10).all()
    if ultimas:
        html += '<div class="painel"><h4>Últimas Candidaturas</h4><table class="tabela"><thead><tr><th>Vaga</th><th>Candidato</th><th>Match Score</th><th>Status</th></tr></thead><tbody>'
        for c in ultimas:
            v = Vaga.query.get(c.vaga_id)
            u = Usuario.query.get(c.candidato_id)
            html += '<tr><td>' + (v.titulo if v else '-') + '</td><td>' + (u.nome if u else '-') + '</td><td><div class="barra" style="min-width:80px;display:inline-block;vertical-align:middle"><span style="width:' + str(int(c.match_score or 0)) + '%"></span></div> <b>' + str(int(c.match_score or 0)) + '%</b></td><td><span class="pill disp">' + c.status + '</span></td></tr>'
        html += '</tbody></table></div>'
    return pagina(html, 'analyt')

# ============ EXPERIÊNCIA ============
@app.route('/experiencia')
def experiencia():
    html = '<h1>Experiência <span>// Jornada do Talento</span></h1><p class="sub">Onboarding digital, mentoria com IA, feedback contínuo e comunidade</p><div class="grade">'
    mods = [
        ('🚀','Onboarding Digital','Jornada guiada para novos candidatos e empresas com gamificação.','#3b82f6'),
        ('🎓','Mentoria com IA','Matching mentor-mentorado e assistente de carreira 24/7.','#10b981'),
        ('💬','Feedback Loop','Feedback bidirecional obrigatório com transparência total.','#f59e0b'),
        ('🗺️','Plano de Carreira','Roadmap personalizado com marcos, prazos e comparação de mercado.','#a855f7'),
        ('🤝','Comunidade','Fóruns, eventos e networking inteligente por objetivos.','#22d3ee'),
        ('🏅','Reconhecimento','Badges e gamificação por conquistas e desenvolvimento.','#ef4444'),
    ]
    for icone, titulo, desc, cor in mods:
        html += '<div class="card" style="cursor:default"><div class="icone" style="background:' + cor + '22">' + icone + '</div><h3>' + titulo + '</h3><p>' + desc + '</p></div>'
    html += '</div>'
    return pagina(html, 'exper')

# ============ INOVAÇÃO ============
@app.route('/inovacao')
def inovacao():
    html = '<h1>Inovação <span>// Futuro do Trabalho</span></h1><p class="sub">Web3, blockchain, Skills DNA, realidade virtual e recrutamento assíncrono</p><div class="grade">'
    mods = [
        ('⛓️','Credenciais Blockchain','Diplomas e certificações verificados como NFTs soulbound.','#3b82f6'),
        ('🧬','Skills DNA','IA descobre skills ocultas e potencial de aprendizado do candidato.','#10b981'),
        ('⏱️','Recrutamento Assíncrono','Processos seletivos sem horário fixo, com desafios práticos.','#f59e0b'),
        ('🥽','VR para Entrevistas','Salas virtuais, visitas ao escritório e assessments imersivos.','#a855f7'),
        ('📜','Contratos Inteligentes','Acordos de trabalho automatizados via blockchain.','#22d3ee'),
        ('🔮','Retenção Preditiva','IA identifica risco de desligamento com até 6 meses de antecedência.','#ef4444'),
    ]
    for icone, titulo, desc, cor in mods:
        html += '<div class="card" style="cursor:default"><div class="icone" style="background:' + cor + '22">' + icone + '</div><h3>' + titulo + '</h3><p>' + desc + '</p></div>'
    html += '</div>'
    return pagina(html, 'inov')

'''
    if marcador in code:
        code = code.replace(marcador, novas_paginas + '\n' + marcador)
        print('✅ 4 novas telas adicionadas (Recrutamento, Analytics, Experiência, Inovação)')
    else:
        print('⚠️ Marcador da API JSON não encontrado — telas não inseridas')

    # ========== 3. MENU DE NAVEGAÇÃO (13 itens) ==========
    old_cab = """def cabecalho(ativo):
    itens = [('/', 'Menu', 'dashboard'), ('/pcs', 'PCS', 'pcs'), ('/vagas', 'Vagas', 'vagas'),
             ('/trilhas', 'Trilhas', 'trilhas'), ('/conectividade', 'Conectividade', 'conect'),
             ('/candidatos', 'Candidatos', 'cand'), ('/empresas', 'Empresas', 'emp'),
             ('/agentes', 'Agentes', 'agent'), ('/login', 'Entrar', 'login')]"""
    new_cab = """def cabecalho(ativo):
    itens = [('/', 'Menu', 'dashboard'), ('/recrutamento', 'Recrutamento', 'recrut'), ('/pcs', 'PCS', 'pcs'),
             ('/vagas', 'Vagas', 'vagas'), ('/trilhas', 'Trilhas', 'trilhas'),
             ('/conectividade', 'Conectividade', 'conect'), ('/candidatos', 'Candidatos', 'cand'),
             ('/empresas', 'Empresas', 'emp'), ('/analytics', 'Analytics', 'analyt'),
             ('/agentes', 'Agentes', 'agent'), ('/experiencia', 'Experiência', 'exper'),
             ('/inovacao', 'Inovação', 'inov'), ('/login', 'Entrar', 'login')]"""
    if old_cab in code:
        code = code.replace(old_cab, new_cab)
        print('✅ Menu de navegação expandido para 13 itens')
    else:
        print('⚠️ Bloco cabecalho não encontrado')

    # ========== 4. CARDS DO MENU PRINCIPAL (9 cards + links corrigidos) ==========
    old_cards = """    cards = [
        ('🧠','Recrutamento Inteligente','IA generativa, matching preditivo e triagem NLP','#3b82f6','/pcs'),
        ('👤','Candidatos','Perfil blockchain, gamificação e match score','#10b981','/candidatos'),
        ('🏢','Empresas','ATS inteligente, employer branding e talent pool','#f59e0b','/empresas'),
        ('📊','Plano de Cargos e Salários','Níveis Júnior a Fellow, faixas e promoções','#a855f7','/pcs'),
        ('📡','Conectividade','Vídeo, WhatsApp, e-mail e chat em tempo real','#22d3ee','/conectividade'),
        ('💼','Vagas','Oportunidades abertas e candidaturas','#ef4444','/vagas'),
    ]"""
    new_cards = """    cards = [
        ('🧠','Recrutamento Inteligente','IA generativa, matching preditivo e triagem NLP','#3b82f6','/recrutamento'),
        ('👤','Candidatos','Perfil blockchain, gamificação e match score','#10b981','/candidatos'),
        ('🏢','Empresas','ATS inteligente, employer branding e talent pool','#f59e0b','/empresas'),
        ('📊','Plano de Cargos e Salários','Níveis Júnior a Fellow, faixas e promoções','#a855f7','/pcs'),
        ('📡','Conectividade','Vídeo, WhatsApp, e-mail e chat em tempo real','#22d3ee','/conectividade'),
        ('💼','Vagas','Oportunidades abertas e candidaturas','#ef4444','/vagas'),
        ('📈','Analytics','People analytics, KPIs e dashboards em tempo real','#f59e0b','/analytics'),
        ('🎯','Experiência','Onboarding, mentoria, feedback e comunidade','#22d3ee','/experiencia'),
        ('🚀','Inovação','Web3, Skills DNA, VR e recrutamento assíncrono','#a855f7','/inovacao'),
    ]"""
    if old_cards in code:
        code = code.replace(old_cards, new_cards)
        print('✅ Cards do menu principal expandidos para 9')
    else:
        print('⚠️ Bloco de cards não encontrado')

    with open(path, 'w', encoding='utf-8') as f:
        f.write(code)
    print('🎉 Patch v3 aplicado com sucesso! Reinicie o servidor.')
