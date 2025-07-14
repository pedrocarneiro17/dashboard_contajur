import os
import re
import sqlite3
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash
import requests
import json
from datetime import datetime

# ⭐ 1. IMPORTAR O MÓDULO LOCALE
import locale

# ⭐ 2. CONFIGURAR O LOCALE PARA PORTUGUÊS DO BRASIL
# Isso fará com que strftime('%B') retorne "janeiro", "fevereiro", etc.
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
except locale.Error:
    print("Locale pt_BR.UTF-8 não encontrado. Usando o locale padrão.")
    # Se o locale não estiver instalado, a aplicação continuará funcionando em inglês.

# --- Configuração da Aplicação ---
app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'
DATABASE = 'financeiro.db'
API_KEY = "AIzaSyA0hJdqhpW0cyaZ6K_ezA82lTMJWOiRO44"

@app.context_processor
def inject_datetime():
    return {'datetime': datetime}

# --- Funções de Banco de Dados e Utilitários ---
def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db

def extrair_mes_ano_do_nome(filename):
    match = re.search(r'(\d{4})-(\d{2})', filename)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return None

# --- Processamento Principal com IA ---
def processar_com_ia_e_salvar(filepath, filename):
    # (Esta função permanece exatamente a mesma da versão anterior)
    if not API_KEY:
        flash("ERRO GRAVE: A chave da API do Gemini não está configurada.", 'error')
        return False
    try:
        df = pd.read_excel(filepath, header=None, engine='openpyxl')
        conteudo_texto = df.to_string()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}"
        prompt = f"""
        Analise o conteúdo da planilha.
        1. Encontre o período do relatório, como "período de 01/06/2025 à 30/06/2025", e extraia o mês e ano. Retorne no formato "AAAA-MM".
        2. Extraia o total de "RECEITAS".
        3. Extraia o total de "DESPESAS".
        4. Extraia a soma de "Honorários", "Honorários CEI" e "Honorários Doméstica".
        Responda APENAS com um JSON no seguinte formato:
        {{"mes": "AAAA-MM", "receitas": VALOR, "despesas": VALOR, "honorarios": VALOR}}
        Use ponto para decimais. Se não encontrar o período, retorne "mes": null.
        --- DADOS ---
        {conteudo_texto}
        """
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        headers = {'Content-Type': 'application/json'}
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code != 200:
            error_data = response.json()
            error_message = error_data.get('error', {}).get('message', 'Erro da API.')
            flash(f"Erro da API Gemini: {error_message}", 'error')
            return False
        response_data = response.json()
        json_text = response_data['candidates'][0]['content']['parts'][0]['text'].strip().replace("```json", "").replace("```", "")
        dados_extraidos = json.loads(json_text)
        mes_ia = dados_extraidos.get("mes")
        if mes_ia:
            mes_arquivo = mes_ia
        else:
            mes_arquivo = extrair_mes_ano_do_nome(filename)
            if not mes_arquivo:
                flash('Mês não encontrado no conteúdo da planilha nem no nome do arquivo.', 'error')
                return False
        receitas = pd.to_numeric(dados_extraidos.get("receitas"), errors='coerce')
        despesas = pd.to_numeric(dados_extraidos.get("despesas"), errors='coerce')
        honorarios = pd.to_numeric(dados_extraidos.get("honorarios"), errors='coerce')
        if any(pd.isna([receitas, despesas, honorarios])):
            flash("A IA não retornou todos os valores financeiros necessários.", 'error')
            return False
        db = get_db()
        db.execute('DELETE FROM relatorios_mensais WHERE mes = ?', (mes_arquivo,))
        db.execute(
            'INSERT INTO relatorios_mensais (mes, total_receitas, total_despesas, total_honorarios) VALUES (?, ?, ?, ?)',
            (mes_arquivo, receitas, despesas, honorarios)
        )
        db.commit()
        db.close()
        flash(f'Relatório de {mes_arquivo} processado com sucesso!', 'success')
        return True
    except Exception as e:
        print(f"Erro no processamento: {e}")
        flash(f"Ocorreu um erro: {e}", 'error')
        return False

# --- Rotas da Aplicação ---
@app.route('/')
def dashboard():
    # (Esta função permanece exatamente a mesma da versão anterior)
    db = get_db()
    meses_disponiveis = db.execute('SELECT mes FROM relatorios_mensais ORDER BY mes DESC').fetchall()
    mes_selecionado = request.args.get('mes', None)
    dados_db = None
    if mes_selecionado:
        dados_db = db.execute('SELECT * FROM relatorios_mensais WHERE mes = ?', (mes_selecionado,)).fetchone()
    elif meses_disponiveis:
        dados_db = db.execute('SELECT * FROM relatorios_mensais ORDER BY mes DESC LIMIT 1').fetchone()
    db.close()
    dados_dashboard = None
    if dados_db:
        lucro = dados_db['total_receitas'] - dados_db['total_despesas']
        margem = (lucro / dados_db['total_receitas']) * 100 if dados_db['total_receitas'] > 0 else 0
        chart_data = {
            "labels": ['Receitas', 'Despesas', 'Honorários'],
            "datasets": [{"label": 'Valores em R$', "data": [dados_db['total_receitas'], dados_db['total_despesas'], dados_db['total_honorarios']], "backgroundColor": ['rgba(75, 192, 192, 0.6)', 'rgba(255, 99, 132, 0.6)', 'rgba(255, 206, 86, 0.6)'], "borderColor": ['rgba(75, 192, 192, 1)', 'rgba(255, 99, 132, 1)', 'rgba(255, 206, 86, 1)'], "borderWidth": 1}]
        }
        dados_dashboard = {
            "mes": dados_db['mes'], "mes_formatado": datetime.strptime(dados_db['mes'], '%Y-%m').strftime('%B de %Y').capitalize(), "total_receitas": dados_db['total_receitas'], "total_despesas": dados_db['total_despesas'], "total_honorarios": dados_db['total_honorarios'], "lucro_liquido": lucro, "margem_lucro": margem, "chart_data": chart_data
        }
    return render_template('dashboard.html', dados=dados_dashboard, meses_disponiveis=meses_disponiveis)

@app.route('/upload', methods=['POST'])
def upload_file():
    # (Esta função permanece exatamente a mesma da versão anterior)
    file = request.files.get('file')
    if not file or not file.filename:
        flash('Nenhum arquivo selecionado.', 'error')
        return redirect(url_for('dashboard'))
    if file.filename.endswith('.xlsx'):
        os.makedirs('uploads', exist_ok=True)
        filepath = os.path.join('uploads', file.filename)
        file.save(filepath)
        processar_com_ia_e_salvar(filepath, file.filename)
    else:
        flash('Formato de arquivo inválido. Por favor, envie um arquivo .xlsx.', 'error')
    return redirect(url_for('dashboard'))

# --- Inicialização ---
def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS relatorios_mensais (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mes TEXT NOT NULL UNIQUE,
                total_receitas REAL NOT NULL,
                total_despesas REAL NOT NULL,
                total_honorarios REAL NOT NULL
            )
        ''')
        db.commit()
        db.close()

if __name__ == '__main__':
    init_db()
    if not API_KEY:
        print("AVISO: A chave da API 'API_KEY' não está configurada.")
    app.run(debug=True)