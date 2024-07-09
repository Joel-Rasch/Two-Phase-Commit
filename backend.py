from flask import Flask, request, jsonify, render_template
from two_phase_commit import TwoPhaseCommit
import os

ZK_HOSTS = os.environ.get('APP_ZOOKEEPER_HOST', 'localhost:2181')

app = Flask(__name__)

# Configuration

DB_CONFIGS = [
    {'dbname': 'db', 'user': 'user', 'password': 'password', 'host': 'postgres1', 'port': '5432'},
    {'dbname': 'db', 'user': 'user', 'password': 'password', 'host': 'postgres2', 'port': '5432'},
    {'dbname': 'db', 'user': 'user', 'password': 'password', 'host': 'postgres3', 'port': '5432'}
]

tpc = TwoPhaseCommit(ZK_HOSTS, DB_CONFIGS)


def createOpenAccountQuery(name, id_number, iban,money):
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


@app.route('/create_account', methods=['POST'])
def create_account():
    try:
        data = request.json
        name = data.get('name')
        id_number = data.get('id_number')
        iban = data.get('iban')
        money = data.get('initial_balance')

        if not all([name, id_number, iban]):
            return jsonify({"error": "Missing required fields"}), 400

        query = createOpenAccountQuery(name, id_number, iban,money)
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
    try:
        data = request.json
        from_iban = data.get('from_iban')
        to_iban = data.get('to_iban')
        amount = data.get('amount')

        if not all([from_iban, to_iban, amount]):
            return jsonify({"error": "Missing required fields"}), 400

        query = createTransferQuery(from_iban, to_iban, amount)
        transaction_path = tpc.create_transaction('APP', 'T', [ query])
        result = tpc.execute_transaction(transaction_path)

        if "committed successfully" in result.lower():
            return jsonify({"message": "Transaction completed successfully"}), 200
        else:
            return jsonify({"error": "Failed to complete transaction"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)