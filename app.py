from flask import Flask, request, render_template, redirect, url_for, flash
import pandas as pd
from datetime import datetime
import os
import re
from werkzeug.utils import secure_filename
import database as db  # Importa nosso novo módulo de banco de dados
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'uma-chave-secreta-muito-forte' # Troque por uma chave segura
app.config['UPLOAD_FOLDER'] = 'Uploads'
app.config['ALLOWED_EXTENSIONS'] = {'xlsx'}
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- INICIALIZAÇÃO DO BANCO DE DADOS ---
# Esta função garante que o banco de dados seja criado assim que o app iniciar.
with app.app_context():
    db.init_db()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def process_excel(file_path):
    # (A sua função process_excel continua aqui, sem alterações)
    try:
        df_header = pd.read_excel(file_path, sheet_name='Página 1', nrows=1, header=None)
        first_row = df_header.iloc[0, 0]
        date_match = re.search(r'(\d{2}/\d{2}/\d{4})\s*à\s*(\d{2}/\d{2}/\d{4})', str(first_row))
        month = datetime.strptime(date_match.group(1), '%d/%m/%Y').strftime('%Y-%m') if date_match else datetime.now().strftime('%Y-%m')
        
        df = pd.read_excel(file_path, sheet_name='Página 1', skiprows=1)
        df['Descrição'] = df['Descrição'].astype(str)
        
        search_column = df.iloc[:, 10].astype(str).str.strip()
        total_revenue = float(pd.to_numeric(df.iloc[df.index[search_column == 'Receitas:'][0], [11, 12]], errors='coerce').sum())
        grand_total_expenses_from_excel = float(pd.to_numeric(df.iloc[df.index[search_column == 'Despesas:'][0], [11, 12]], errors='coerce').sum())
    except Exception as e:
        raise ValueError(f"Erro ao ler os totais de Receita/Despesa do Excel. Detalhe: {e}")

    withdrawal_names = ['Retirada Lucas', 'Retirada Thiago', 'Retirada Ronaldo']
    withdrawals_df = df[df['Descrição'].str.strip().isin(withdrawal_names)]
    total_withdrawals_from_excel = float(pd.to_numeric(withdrawals_df['Total'], errors='coerce').fillna(0).sum())

    total_expenses = grand_total_expenses_from_excel - total_withdrawals_from_excel
    profit_before_withdrawals = total_revenue - total_expenses
    net_profit = profit_before_withdrawals
    profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0

    initial_profit_share = profit_before_withdrawals / 4.0
    shares = { 'Lucas': initial_profit_share, 'Thiago': initial_profit_share, 'Ronaldo': initial_profit_share, 'Reserva': initial_profit_share }
    
    for _, row in withdrawals_df.iterrows():
        amount = pd.to_numeric(row['Total'], errors='coerce')
        if pd.notna(amount) and amount != 0:
            person = row['Descrição'].replace('Retirada ', '').strip()
            if person in shares: shares[person] -= float(amount)

    honorarios = df[df['Descrição'].str.strip().isin(['Honorarios', 'Honorarios CEI', 'Honorarios Doméstica'])]['Total']
    total_fees = float(honorarios.sum()) if not honorarios.empty else 0.0

    totals_data = {
        "month": month, "total_revenue": total_revenue, "total_expenses": total_expenses, 
        "total_fees": total_fees, "net_profit": net_profit, "profit_margin": profit_margin,
        "share_lucas": shares['Lucas'], "share_thiago": shares['Thiago'],
        "share_ronaldo": shares['Ronaldo'], "share_reserva": shares['Reserva']
    }
    
    expenses_data = []
    categories = {
        'Despesas com Colaboradores': ['Salários', 'Férias', 'Vale transporte', 'Vale alimentação', 'Plano de Saude', 'Plano Odontologico', 'Aniversário colaboradores', 'Mensalidade Personal', 'Mensalidade Rede Cidada', 'Seguro de vida', 'Feira, Mercado e outros', 'SST', 'Cursos e Palestras'],
        'Despesas com Impostos': ['DAS - CONTAJUR', 'DARF CONTAJUR', 'FGTS - CONTAJUR'],
        'Despesas de Escritório': ['Luz', 'Telefonia', 'Internet', 'Aluguel', 'Materiais de limpeza', 'Uniformes'],
        'Mensalidades': ['Mensalidade de Sistema', 'Mensalidade T.I.', 'Mensalidade Marketing Digital', 'Mensalidade Revista Tecnica', 'Mensalidade Aluguel de Impressora', 'Mensalidade Associal Comercial', 'Segurança', 'Implantação Sistema'],
        'Manutenção': ['Manutenção Contajur (pintura, reforma, etc.)', 'Manutenção Equipamentos e materiais', 'Material de escritório', 'Material de uso e consumo'],
        'Outras Despesas': ['Tarifa Bancaria', 'Abertura,baixa e alteração JUCEMG - Cliente', 'Reembolso Certificado Digital', 'Outras despesas', 'Patrocínio/doações', 'Combustivel e Manutençao Motos']
    }
    for category, subcategories in categories.items():
        rows = df[df['Descrição'].str.strip().isin(subcategories)]
        for _, row in rows.iterrows():
            amount = pd.to_numeric(row['Total'], errors='coerce')
            if pd.notna(amount) and amount != 0:
                expenses_data.append((month, category, row['Descrição'], float(amount)))

    withdrawals_data = []
    for _, row in withdrawals_df.iterrows():
        amount = pd.to_numeric(row['Total'], errors='coerce')
        if pd.notna(amount) and amount != 0:
            person = row['Descrição'].replace('Retirada ', '').strip()
            withdrawals_data.append((month, person, float(amount), 'excel'))

    db.save_processed_excel_data(month, totals_data, expenses_data, withdrawals_data)
    
    return month


@app.route('/', methods=['GET', 'POST'])
def dashboard():
    error = None
    if request.method == 'POST' and 'file' in request.files:
        file = request.files['file']
        if file.filename == '':
            error = 'Nenhum arquivo selecionado'
        elif file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            try:
                processed_month = process_excel(file_path)
                flash(f'Relatório do mês {processed_month} processado com sucesso!', 'success')
                return redirect(url_for('dashboard', month=processed_month))
            except ValueError as e:
                error = str(e)
        else:
            error = 'Extensão de arquivo não permitida. Use .xlsx'

    all_months = db.get_available_months()
    selected_month = request.args.get('month', all_months[0] if all_months else None)
    
    dashboard_data = db.get_dashboard_data(selected_month)
    
    return render_template('dashboard.html', 
                           months=all_months, 
                           selected_month=selected_month, 
                           error=error,
                           **dashboard_data)

@app.route('/add_withdrawal', methods=['POST'])
def add_withdrawal():
    month = request.form.get('month')
    person = request.form.get('person')
    amount_str = request.form.get('amount')
    try:
        amount = float(amount_str)
        db.add_manual_withdrawal(month, person, amount)
        flash(f'Retirada de {person} adicionada com sucesso!', 'success')
    except (ValueError, TypeError):
        flash('Erro: O valor da retirada deve ser um número.', 'error')
    
    return redirect(url_for('dashboard', month=month))

@app.route('/delete_withdrawal/<int:withdrawal_id>', methods=['POST'])
def delete_withdrawal(withdrawal_id):
    success, message = db.delete_manual_withdrawal(withdrawal_id)
    if success:
        flash('Retirada excluída com sucesso!', 'success')
    else:
        flash(f'Erro: {message}', 'error')
    
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/delete/<string:month>', methods=['POST'])
def delete_month(month):
    try:
        db.delete_all_month_data(month)
        flash(f"Dados do mês {month} excluídos com sucesso.", 'success')
    except Exception as e:
        flash(f"Erro ao excluir o mês {month}: {e}", 'error')
    return redirect(url_for('dashboard'))

@app.route('/compare')
def compare():
    selected_months = request.args.getlist('month')
    if not selected_months or len(selected_months) < 2:
        flash("Por favor, selecione pelo menos dois meses para comparar.", "error")
        return redirect(url_for('dashboard'))
    
    selected_months.sort()
    
    totals_comparison, category_comparison = db.get_compare_data(selected_months)
    
    return render_template('compare.html', 
                           selected_months=selected_months,
                           totals_comparison=totals_comparison,
                           category_comparison=category_comparison)
