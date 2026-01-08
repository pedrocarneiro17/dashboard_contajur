import sqlite3
import os
from collections import defaultdict

DATABASE = os.path.join("/mnt/data/", "contajur.db")

def get_db_connection():
    """Cria uma conexão com o banco de dados."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Permite acessar colunas por nome
    return conn

def init_db():
    """Cria as tabelas do banco de dados se elas não existirem."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY, month TEXT, category TEXT, subcategory TEXT, amount REAL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS totals (
            id INTEGER PRIMARY KEY, month TEXT UNIQUE, total_revenue REAL,
            total_expenses REAL, total_fees REAL, net_profit REAL, profit_margin REAL,
            share_lucas REAL, share_thiago REAL, share_ronaldo REAL, share_reserva REAL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY, month TEXT, person TEXT, amount REAL,
            source TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()

def save_processed_excel_data(month, totals_data, expenses_data, withdrawals_data):
    """Salva todos os dados processados de um arquivo Excel de forma transacional."""
    with get_db_connection() as conn:
        c = conn.cursor()
        # Limpa dados antigos do mês para evitar duplicatas
        c.execute('DELETE FROM expenses WHERE month = ?', (month,))
        c.execute('DELETE FROM totals WHERE month = ?', (month,))
        c.execute('DELETE FROM withdrawals WHERE month = ? AND source = ?', (month, 'excel'))

        # Insere os novos totais
        c.execute('''INSERT INTO totals (month, total_revenue, total_expenses, total_fees, net_profit, 
                     profit_margin, share_lucas, share_thiago, share_ronaldo, share_reserva)
                     VALUES (:month, :total_revenue, :total_expenses, :total_fees, :net_profit, 
                     :profit_margin, :share_lucas, :share_thiago, :share_ronaldo, :share_reserva)''', 
                     totals_data)

        # Insere as despesas e retiradas em lote (mais eficiente)
        c.executemany('INSERT INTO expenses (month, category, subcategory, amount) VALUES (?, ?, ?, ?)', expenses_data)
        c.executemany('INSERT INTO withdrawals (month, person, amount, source) VALUES (?, ?, ?, ?)', withdrawals_data)
        
        conn.commit()

def add_manual_withdrawal(month, person, amount):
    """Adiciona uma retirada manual e atualiza os totais correspondentes."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO withdrawals (month, person, amount, source) VALUES (?, ?, ?, ?)",
                  (month, person, amount, 'manual'))
        
        # Retiradas manuais afetam apenas a distribuição do lucro, não o lucro líquido principal
        share_column = f"share_{person.lower()}"
        c.execute(f"UPDATE totals SET {share_column} = {share_column} - ? WHERE month = ?", (amount, month))
        
        conn.commit()

def delete_manual_withdrawal(withdrawal_id):
    """Deleta uma retirada manual e reverte as alterações nos totais."""
    with get_db_connection() as conn:
        c = conn.cursor()
        withdrawal = c.execute("SELECT * FROM withdrawals WHERE id = ?", (withdrawal_id,)).fetchone()
        
        if withdrawal:
            amount = withdrawal['amount']
            month = withdrawal['month']
            person = withdrawal['person']
            
            c.execute("DELETE FROM withdrawals WHERE id = ?", (withdrawal_id,))
            
            # Reverte a alteração na distribuição do lucro
            share_column = f"share_{person.lower()}"
            c.execute(f"UPDATE totals SET {share_column} = {share_column} + ? WHERE month = ?", (amount, month))
            
            conn.commit()
            return True, ""
    return False, "Retirada não encontrada."

def get_dashboard_data(selected_month):
    """Busca todos os dados necessários para renderizar o dashboard de um mês."""
    data = {
        "totals": None, "expenses": {}, "revenue_in_mw": 0,
        "top_10_chart_data": None, "withdrawals_list": [], 
        "fees_in_mw": 0
    }
    if not selected_month:
        return data

    with get_db_connection() as conn:
        c = conn.cursor()
        
        # Totais e cálculo de Salário Mínimo
        totals_row = c.execute('SELECT * FROM totals WHERE month = ?', (selected_month,)).fetchone()
        if totals_row:
            data['totals'] = dict(totals_row)
            if data['totals'].get('total_revenue', 0) > 0:
                data['revenue_in_mw'] = data['totals']['total_revenue'] / 1518.0

        if data['totals'].get('total_fees', 0) > 0:
            data['fees_in_mw'] = data['totals']['total_fees'] / 1518.0

        # Top 10 Despesas
        top_10_rows = c.execute('SELECT subcategory, amount FROM expenses WHERE month = ? ORDER BY amount DESC LIMIT 10', (selected_month,)).fetchall()
        if top_10_rows:
            data['top_10_chart_data'] = {
                'labels': [row['subcategory'] for row in top_10_rows],
                'data': [row['amount'] for row in top_10_rows]
            }
        
        # ORDEM FIXA DAS CATEGORIAS
        category_order = [
            'Despesas com Pessoal',
            'Impostos e Encargos',
            'Despesas de Escritório',
            'Mensalidades e Serviços',
            'Manutenção e Investimentos',
            'Reembolsos a Clientes',
            'Outras Despesas'
        ]
        
        # Inicializa todas as categorias na ordem correta (mesmo vazias)
        for category in category_order:
            data['expenses'][category] = []
        
        # Despesas detalhadas com percentual
        expense_rows = c.execute('SELECT category, subcategory, amount FROM expenses WHERE month = ?', (selected_month,)).fetchall()
        category_totals = defaultdict(float)
        for row in expense_rows:
            category_totals[row['category']] += row['amount']
        
        for row in expense_rows:
            category, amount = row['category'], row['amount']
            total = category_totals[category]
            percentage = (amount / total * 100) if total > 0 else 0
            if category in data['expenses']:  # Só adiciona se a categoria existir na ordem
                data['expenses'][category].append({'subcategory': row['subcategory'], 'amount': amount, 'percentage': percentage})

        # Remove categorias vazias
        data['expenses'] = {k: v for k, v in data['expenses'].items() if v}

        # Lista de Retiradas
        data['withdrawals_list'] = c.execute('SELECT * FROM withdrawals WHERE month = ? ORDER BY timestamp DESC', (selected_month,)).fetchall()
        
    return data

def get_available_months():
    """Busca a lista de meses disponíveis."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('SELECT DISTINCT month FROM totals ORDER BY month DESC')
        return [row['month'] for row in c.fetchall()]

def delete_all_month_data(month):
    """Deleta todos os dados de um mês específico."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('DELETE FROM expenses WHERE month = ?', (month,))
        c.execute('DELETE FROM totals WHERE month = ?', (month,))
        c.execute('DELETE FROM withdrawals WHERE month = ?', (month,))
        conn.commit()
        
# Adicione esta função ao final do seu arquivo database.py

def get_compare_data(selected_months):
    """Busca e prepara os dados para a página de comparação de meses."""
    with get_db_connection() as conn:
        placeholders = ','.join('?' for _ in selected_months)
        
        # 1. Buscar dados da tabela 'totals'
        totals_data_rows = conn.execute(
            f"SELECT * FROM totals WHERE month IN ({placeholders}) ORDER BY month", 
            selected_months
        ).fetchall()

        # 2. Buscar e agregar despesas por categoria
        expenses_data_rows = conn.execute(
            f"SELECT month, category, SUM(amount) as total FROM expenses WHERE month IN ({placeholders}) GROUP BY month, category ORDER BY month", 
            selected_months
        ).fetchall()

    # 3. Preparar dados para o gráfico de linhas (Receita, Despesa, Lucro)
    totals_comparison = {
        'labels': [row['month'] for row in totals_data_rows],
        'datasets': [
            {'label': 'Total de Receitas', 'data': [row['total_revenue'] for row in totals_data_rows], 'borderColor': '#10B981', 'tension': 0.1},
            {'label': 'Total de Despesas', 'data': [row['total_expenses'] for row in totals_data_rows], 'borderColor': '#EF4444', 'tension': 0.1},
            {'label': 'Lucro Líquido', 'data': [row['net_profit'] for row in totals_data_rows], 'borderColor': '#3B82F6', 'tension': 0.1},
            {'label': 'Honorários', 'data': [row['total_fees'] for row in totals_data_rows], 'borderColor': '#F59E0B', 'tension': 0.1}
        ]
    }

    # 4. Preparar dados para o gráfico de barras (comparação de categorias)
    category_comparison_data = defaultdict(lambda: [0] * len(selected_months))
    category_totals_for_sorting = defaultdict(float)

    for row in expenses_data_rows:
        month_index = selected_months.index(row['month'])
        category_comparison_data[row['category']][month_index] = row['total']
        category_totals_for_sorting[row['category']] += row['total']
    
    sorted_categories = sorted(category_totals_for_sorting.keys(), key=lambda cat: category_totals_for_sorting[cat], reverse=True)
    
    category_comparison = {
        'labels': selected_months,
        'datasets': [{'label': cat, 'data': category_comparison_data[cat]} for cat in sorted_categories]
    }
    
    return totals_comparison, category_comparison