from flask import Flask, request, jsonify, render_template  
from two_phase_commit import TwoPhaseCommit  
import os  
import psycopg  
from flask_cors import CORS

  
ZK_HOSTS = os.environ.get('APP_ZOOKEEPER_HOST', 'localhost:2181')  
app = Flask(__name__)  
CORS(app)  # Enable CORS for all routes  
  
# Configuration  
DB_CONFIGS = [  
    {'dbname': 'db', 'user': 'user', 'password': 'password', 'host': 'postgres1', 'port': '5432'},  
    {'dbname': 'db', 'user': 'user', 'password': 'password', 'host': 'postgres2', 'port': '5432'},  
    {'dbname': 'db', 'user': 'user', 'password': 'password', 'host': 'postgres3', 'port': '5432'}  
]  
db_enabled = [True, True, True]  # Global variable to keep track of enabled databases  
  
tpc = TwoPhaseCommit(ZK_HOSTS, DB_CONFIGS)  
tpc.db_enabled = db_enabled  # Pass db_enabled to TwoPhaseCommit  
  
def createOpenAccountQuery(name, id_number, iban, money):  
    query = f"""  
    DO $$  
    BEGIN  
        IF EXISTS (SELECT 1 FROM accounts WHERE iban = '{iban}') THEN  
            RAISE EXCEPTION 'Ein Konto mit der IBAN % existiert bereits.', '{iban}';  
        ELSE  
            INSERT INTO accounts (name, id_number, iban, balance)  
            VALUES ('{name}', '{id_number}', '{iban}', {money});  
        END IF;  
    END $$;  
    """  
    return query  
  
def createTransferQuery(RemitterIBAN, ReceiverIBAN, amount):  
    query = f"""  
    DO $$  
    DECLARE  
        remitter_balance DECIMAL;  
    BEGIN  
        IF NOT EXISTS (SELECT 1 FROM accounts WHERE iban = '{RemitterIBAN}') THEN  
            RAISE EXCEPTION 'Das Konto mit der IBAN % existiert nicht.', '{RemitterIBAN}';  
        ELSIF NOT EXISTS (SELECT 1 FROM accounts WHERE iban = '{ReceiverIBAN}') THEN  
            RAISE EXCEPTION 'Das Konto mit der IBAN % existiert nicht.', '{ReceiverIBAN}';  
        ELSE  
            SELECT balance INTO remitter_balance FROM accounts WHERE iban = '{RemitterIBAN}';  
            IF remitter_balance < {amount} THEN  
                RAISE EXCEPTION 'Das Konto mit der IBAN % hat nicht genügend Guthaben.', '{RemitterIBAN}';  
            ELSE  
                UPDATE accounts SET balance = balance - {amount} WHERE iban = '{RemitterIBAN}';  
                UPDATE accounts SET balance = balance + {amount} WHERE iban = '{ReceiverIBAN}';  
                INSERT INTO transactions (from_account, to_account, amount)  
                VALUES ('{RemitterIBAN}', '{ReceiverIBAN}', {amount});  
            END IF;  
        END IF;  
    END $$;  
    """  
    return query  
  
@app.route('/')  
def index():  
    return render_template('index.html')  
  
@app.route('/db_status')  
def db_status():  
    statuses = []  
    for i, config in enumerate(DB_CONFIGS):  
        if not db_enabled[i]:  
            statuses.append({'db': f'DB_{i+1}', 'status': 'disabled'})  
            continue  
        try:  
            with psycopg.connect(**config) as conn:  
                with conn.cursor() as cur:  
                    cur.execute('SELECT 1;')  
            statuses.append({'db': f'DB_{i+1}', 'status': 'online'})  
        except Exception as e:  
            statuses.append({'db': f'DB_{i+1}', 'status': 'offline'})  
    return jsonify(statuses)  
  
@app.route('/accounts')  
def get_accounts():  
    # Return combined data from all enabled databases  
    combined_data = []  
    for i, config in enumerate(DB_CONFIGS):  
        if not db_enabled[i]:  
            continue  
        try:  
            with psycopg.connect(**config) as conn:  
                with conn.cursor() as cur:  
                    cur.execute('SELECT * FROM accounts;')  
                    rows = cur.fetchall()  
                    colnames = [desc[0] for desc in cur.description]  
            data = [dict(zip(colnames, row)) for row in rows]  
            combined_data.extend(data)  
        except Exception:  
            continue  
    if combined_data:  
        return jsonify(combined_data)  
    else:  
        return jsonify({'error': 'No databases available'}), 500  
  
@app.route('/accounts/<int:db_index>')  
def get_accounts_db(db_index):  
    if not (0 <= db_index < len(DB_CONFIGS)):  
        return jsonify({'error': 'Invalid database index'}), 400  
    if not db_enabled[db_index]:  
        return jsonify({'error': 'Database is disabled'}), 400  
    config = DB_CONFIGS[db_index]  
    try:  
        with psycopg.connect(**config) as conn:  
            with conn.cursor() as cur:  
                cur.execute('SELECT * FROM accounts;')  
                rows = cur.fetchall()  
                colnames = [desc[0] for desc in cur.description]  
        data = [dict(zip(colnames, row)) for row in rows]  
        return jsonify(data)  
    except Exception as e:  
        return jsonify({'error': str(e)}), 500  
  
@app.route('/create_account', methods=['POST'])  
def create_account():  
    try:
        tpc = TwoPhaseCommit(ZK_HOSTS, DB_CONFIGS)  
        tpc.db_enabled = db_enabled  # Pass db_enabled to TwoPhaseCommit  
        data = request.get_json()  
        if data is None:  
            return jsonify({"error": "Invalid JSON data"}), 400  
        name = data.get('name')  
        id_number = data.get('id_number')  
        iban = data.get('iban')  
        money = data.get('initial_balance')  
        if not all([name, id_number, iban, money]):  
            return jsonify({"error": "Missing required fields"}), 400  
        query = createOpenAccountQuery(name, id_number, iban, money)  
        transaction_path = tpc.create_transaction('APP', 'T', [query])  
        result = tpc.execute_transaction(transaction_path)  
        if "committed successfully" in result.lower():  
            return jsonify({"message": "Account created successfully"}), 201  
        else:  
            return jsonify({"error": "Failed to create account"}), 500  
    except Exception as e:  
        return jsonify({"error": str(e)}), 500  
  
@app.route('/perform_transaction', methods=['POST'])  
def perform_transaction():
    tpc = TwoPhaseCommit(ZK_HOSTS, DB_CONFIGS)  
    tpc.db_enabled = db_enabled  # Pass db_enabled to TwoPhaseCommit  
    try:  
        data = request.get_json()  
        if data is None:  
            return jsonify({"error": "Invalid JSON data"}), 400  
        from_iban = data.get('from_iban')  
        to_iban = data.get('to_iban')  
        amount = data.get('amount')  
        if not all([from_iban, to_iban, amount]):  
            return jsonify({"error": "Missing required fields"}), 400  
        query = createTransferQuery(from_iban, to_iban, amount)  
        transaction_path = tpc.create_transaction('APP', 'T', [query])  
        result = tpc.execute_transaction(transaction_path)  
        if "committed successfully" in result.lower():  
            return jsonify({"message": "Transaction completed successfully"}), 200  
        else:  
            return jsonify({"error": "Failed to complete transaction"}), 500  
    except Exception as e:  
        return jsonify({"error": str(e)}), 500  
  
if __name__ == '__main__':  
    app.run(debug=True, host='0.0.0.0')  
