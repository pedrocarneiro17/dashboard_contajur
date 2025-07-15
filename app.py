from flask import Flask, request, render_template, redirect, url_for
import pandas as pd
import sqlite3
from datetime import datetime
import os
import re
from werkzeug.utils import secure_filename
from collections import defaultdict

# ... (o início do app.py, init_db, process_excel, etc., continuam iguais) ...
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'Uploads'
app.config['ALLOWED_EXTENSIONS'] = {'xlsx'}

pd.set_option('future.no_silent_downcasting', True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def init_db():
    with sqlite3.connect('expenses.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT,
            category TEXT,
            subcategory TEXT,
            amount REAL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS totals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT UNIQUE,
            total_revenue REAL,
            total_expenses REAL,
            total_fees REAL,
            net_profit REAL,
            profit_margin REAL
        )''')
        conn.commit()

def process_excel(file_path):
    # (A função process_excel continua a mesma da nossa última versão)
    df_header = pd.read_excel(file_path, sheet_name='Página 1', nrows=1, header=None)
    first_row = df_header.iloc[0, 0]
    date_match = re.search(r'(\d{2}/\d{2}/\d{4})\s*à\s*(\d{2}/\d{2}/\d{4})', str(first_row))
    if date_match:
        start_date = date_match.group(1)
        month = datetime.strptime(start_date, '%d/%m/%Y').strftime('%Y-%m')
    else:
        month = datetime.now().strftime('%Y-%m')
    df = pd.read_excel(file_path, sheet_name='Página 1', skiprows=1)
    try:
        search_column = df.iloc[:, 10].astype(str).str.strip()
        revenue_row_list = df.index[search_column == 'Receitas:'].tolist()
        if not revenue_row_list:
            raise ValueError("Não foi possível encontrar o texto 'Receitas:' na coluna K.")
        revenue_row_index = revenue_row_list[0]
        revenue_values = df.iloc[revenue_row_index, [11, 12]].replace('', 0).fillna(0)
        total_revenue = float(pd.to_numeric(revenue_values, errors='coerce').sum())
        expense_row_list = df.index[search_column == 'Despesas:'].tolist()
        if not expense_row_list:
            raise ValueError("Não foi possível encontrar o texto 'Despesas:' na coluna K.")
        expense_row_index = expense_row_list[0]
        expenses_values = df.iloc[expense_row_index, [11, 12]].replace('', 0).fillna(0)
        total_expenses = float(pd.to_numeric(expenses_values, errors='coerce').sum())
        if pd.isna(total_revenue) or pd.isna(total_expenses):
            raise ValueError("Valores de totais não são numéricos nas colunas L e M da linha encontrada.")
    except (IndexError, KeyError) as e:
        raise ValueError(f"Erro ao processar o arquivo Excel: {e}. Verifique se a coluna K contém os textos 'Receitas:' e 'Despesas:'.")
    honorarios = df[df['Descrição'].str.strip().isin(['Honorarios', 'Honorarios CEI', 'Honorarios Doméstica'])]['Total']
    total_fees = float(honorarios.sum()) if not honorarios.empty else 0.0
    net_profit = total_revenue - total_expenses
    profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
    categories = {
        'Despesas com Colaboradores': ['Salários', 'Férias', 'Vale transporte', 'Vale alimentação', 'Plano de Saude', 'Plano Odontologico', 'Aniversário colaboradores', 'Mensalidade Personal', 'Mensalidade Rede Cidada', 'Seguro de vida', 'Feira, Mercado e outros', 'SST', 'Cursos e Palestras'],
        'Despesas com Impostos': ['DAS - CONTAJUR', 'DARF CONTAJUR', 'FGTS - CONTAJUR'],
        'Despesas de Escritório': ['Luz', 'Telefonia', 'Internet', 'Aluguel', 'Materiais de limpeza', 'Uniformes'],
        'Mensalidades': ['Mensalidade de Sistema', 'Mensalidade T.I.', 'Mensalidade Marketing Digital', 'Mensalidade Revista Tecnica', 'Mensalidade Aluguel de Impressora', 'Mensalidade Associal Comercial', 'Segurança', 'Implantação Sistema'],
        'Manutenção': ['Manutenção Contajur (pintura, reforma, etc.)', 'Manutenção Equipamentos e materiais', 'Material de escritório', 'Material de uso e consumo'],
        'Outras Despesas': ['Tarifa Bancaria', 'Abertura,baixa e alteração JUCEMG - Cliente', 'Reembolso Certificado Digital', 'Outras despesas', 'Patrocínio/doações', 'Combustivel e Manutençao Motos']
    }
    with sqlite3.connect('expenses.db') as conn:
        c = conn.cursor()
        c.execute('DELETE FROM expenses WHERE month = ?', (month,))
        c.execute('DELETE FROM totals WHERE month = ?', (month,))
        c.execute('''INSERT OR REPLACE INTO totals (month, total_revenue, total_expenses, total_fees, net_profit, profit_margin)
                      VALUES (?, ?, ?, ?, ?, ?)''', (month, total_revenue, total_expenses, total_fees, net_profit, profit_margin))
        for category, subcategories in categories.items():
            rows = df.loc[df['Descrição'].str.strip().isin(subcategories)]
            if not rows.empty:
                for _, row in rows.iterrows():
                    subcategory = row['Descrição']
                    amount_value = pd.to_numeric(row['Total'], errors='coerce')
                    if pd.notna(amount_value):
                        amount = float(amount_value)
                        if amount != 0:
                            c.execute('INSERT INTO expenses (month, category, subcategory, amount) VALUES (?, ?, ?, ?)',
                                      (month, category, subcategory, amount))
        conn.commit()
    return month

### ROTA DASHBOARD ATUALIZADA ###
### ROTA DASHBOARD ATUALIZADA ###
@app.route('/', methods=['GET', 'POST'])
def dashboard():
    error = None
    # Lógica de Upload de Arquivo
    if request.method == 'POST':
        if 'file' not in request.files or request.files['file'].filename == '':
            error = 'Nenhum arquivo selecionado'
        else:
            file = request.files['file']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                try:
                    processed_month = process_excel(file_path)
                    return redirect(url_for('dashboard', month=processed_month))
                except ValueError as e:
                    error = str(e)
            else:
                error = 'Extensão de arquivo não permitida. Use .xlsx'

    # Lógica de Exibição de Dados
    with sqlite3.connect('expenses.db') as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute('SELECT DISTINCT month FROM expenses ORDER BY month DESC')
        all_months = [row['month'] for row in c.fetchall()]
        
        selected_month = request.args.get('month', all_months[0] if all_months else None)
        
        expenses = defaultdict(list)
        totals = None
        category_totals = defaultdict(float)
        # --- NOVAS VARIÁVEIS ---
        revenue_in_mw = 0
        top_10_chart_data = None
        
        if selected_month:
            # Fetch totals
            c.execute('SELECT * FROM totals WHERE month = ?', (selected_month,))
            totals_row = c.fetchone()
            if totals_row:
                totals = dict(totals_row)
                # NOVO: Cálculo de salários mínimos
                salario_minimo = 1518.0
                if totals and totals['total_revenue'] > 0:
                    revenue_in_mw = totals['total_revenue'] / salario_minimo

            # NOVO: Fetch dados para o gráfico Top 10 Despesas
            c.execute('SELECT subcategory, amount FROM expenses WHERE month = ? ORDER BY amount DESC LIMIT 10', (selected_month,))
            top_10_expenses_rows = c.fetchall()
            if top_10_expenses_rows:
                top_10_chart_data = {
                    'labels': [row['subcategory'] for row in top_10_expenses_rows],
                    'data': [row['amount'] for row in top_10_expenses_rows]
                }
            
            # Fetch all expenses for the month
            c.execute('SELECT category, subcategory, amount FROM expenses WHERE month = ? ORDER BY category, amount DESC', (selected_month,))
            rows = c.fetchall()

            for row in rows:
                category_totals[row['category']] += row['amount']
            
            for row in rows:
                category = row['category']
                amount = row['amount']
                total_for_category = category_totals[category]
                percentage = (amount / total_for_category * 100) if total_for_category > 0 else 0
                expenses[category].append({
                    'subcategory': row['subcategory'], 
                    'amount': amount,
                    'percentage': percentage
                })

    return render_template('dashboard.html', 
                           months=all_months, 
                           selected_month=selected_month, 
                           expenses=expenses, 
                           totals=totals, 
                           error=error,
                           # --- PASSANDO AS NOVAS VARIÁVEIS PARA O TEMPLATE ---
                           revenue_in_mw=revenue_in_mw,
                           top_10_chart_data=top_10_chart_data)
    
### ROTA DE COMPARAÇÃO ATUALIZADA ###
@app.route('/compare')
def compare():
    selected_months = request.args.getlist('month')
    if not selected_months or len(selected_months) < 2:
        return redirect(url_for('dashboard'))

    # Ordena os meses para os gráficos ficarem na ordem cronológica
    selected_months.sort()
    
    with sqlite3.connect('expenses.db') as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        placeholders = ','.join('?' for _ in selected_months)

        # 1. Buscar dados da tabela 'totals'
        c.execute(f"SELECT * FROM totals WHERE month IN ({placeholders}) ORDER BY month", selected_months)
        totals_data = c.fetchall()

        # 2. Buscar e agregar despesas por categoria
        c.execute(f"SELECT month, category, SUM(amount) as total FROM expenses WHERE month IN ({placeholders}) GROUP BY month, category ORDER BY month", selected_months)
        expenses_data = c.fetchall()
    
    # 3. Preparar dados para os gráficos
    # Dados para o gráfico de linhas (Receita, Despesa, Lucro)
    totals_comparison = {
        'labels': [row['month'] for row in totals_data],
        'datasets': [
            {'label': 'Total de Receitas', 'data': [row['total_revenue'] for row in totals_data], 'borderColor': '#10B981', 'tension': 0.1},
            {'label': 'Total de Despesas', 'data': [row['total_expenses'] for row in totals_data], 'borderColor': '#EF4444', 'tension': 0.1},
            {'label': 'Lucro Líquido', 'data': [row['net_profit'] for row in totals_data], 'borderColor': '#3B82F6', 'tension': 0.1},
        ]
    }

    # Dados para o gráfico de barras (comparação de categorias)
    category_comparison_data = defaultdict(lambda: [0] * len(selected_months))
    
    # NOVO: Calcular o total de cada categoria nos meses selecionados para ordenação
    category_totals_for_sorting = defaultdict(float)

    for row in expenses_data:
        month_index = selected_months.index(row['month'])
        category_comparison_data[row['category']][month_index] = row['total']
        # Soma o total da categoria para usar na ordenação
        category_totals_for_sorting[row['category']] += row['total']
    
    # NOVO: Ordenar as categorias pelo total geral (do maior para o menor)
    sorted_categories = sorted(
        category_totals_for_sorting.keys(), 
        key=lambda cat: category_totals_for_sorting[cat], 
        reverse=True
    )
    
    category_comparison = {
        'labels': selected_months,
        # Usa a lista de categorias já ordenada para criar os datasets
        'datasets': [{'label': cat, 'data': category_comparison_data[cat]} for cat in sorted_categories]
    }
    
    return render_template('compare.html', 
                           selected_months=selected_months,
                           totals_comparison=totals_comparison,
                           category_comparison=category_comparison)

# ... (A rota /delete e o final do arquivo continuam os mesmos) ...
@app.route('/delete/<string:month>', methods=['POST'])
def delete_month(month):
    """
    Exclui todos os dados de um mês específico das tabelas 'expenses' e 'totals'.
    """
    try:
        with sqlite3.connect('expenses.db') as conn:
            c = conn.cursor()
            
            # Exclui da tabela de despesas
            c.execute('DELETE FROM expenses WHERE month = ?', (month,))
            
            # Exclui da tabela de totais
            c.execute('DELETE FROM totals WHERE month = ?', (month,))
            
            conn.commit()
            print(f"Dados do mês {month} excluídos com sucesso.")
            
    except Exception as e:
        print(f"Erro ao excluir o mês {month}: {e}")

    # Redireciona de volta para o dashboard principal
    return redirect(url_for('dashboard'))

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True)