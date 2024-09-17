from kazoo.client import KazooClient
import psycopg

class TwoPhaseCommit:
    def __init__(self, zk_hosts, db_configs):
        self.zk = KazooClient(hosts=zk_hosts)
        self.zk.start()
        self.db_configs = db_configs
        self.db_connections = [psycopg.connect(**config, autocommit=False) for config in db_configs]
        self.db_enabled = [True] * len(self.db_connections)

    def begin_phase(self, transaction_path):
        participants = self.zk.get_children(f'{transaction_path}/participants')
        results = []
        any_enabled = False  # Flag to check if any database is enabled
        for participant in participants:
            index = int(participant.split('_')[1])
            if not self.db_enabled[index]:
                continue
            any_enabled = True
            result = self.begin_participant(transaction_path, participant, index)
            results.append(result)
            if not result:
                return False  # Abort if any begin fails
        return any_enabled and all(results)

    def begin_participant(self, transaction_path, participant, index):
        conn = self.db_connections[index]
        try:
            conn.autocommit = False
            self.zk.set(f'{transaction_path}/participants/{participant}', b'STARTED')
            return True
        except Exception as e:
            return False

    def create_transaction(self, root_name, transaction_name, queries):
        try:
            self.zk.ensure_path(f'/{root_name}')
            transaction_id = len(self.zk.get_children(f'/{root_name}'))
            transaction_path = self.zk.create(f'/{root_name}/{transaction_name}_{transaction_id}', b'NEW', makepath=True, sequence=False)
            self.zk.ensure_path(f'{transaction_path}/queries')
            self.zk.ensure_path(f'{transaction_path}/participants')

            for i, query in enumerate(queries):
                self.zk.create(f'{transaction_path}/queries/q_{i}', query.encode())

            for i in range(len(self.db_connections)):
                self.zk.create(f'{transaction_path}/participants/P_{i}', b'NEW')

            return transaction_path
        except Exception as e:
            raise

    def execute_transaction(self, transaction_path):
        try:
            if (self.begin_phase(transaction_path) and
                self.prepare_phase(transaction_path) and
                self.commit_phase(transaction_path)):
                return "Transaction committed successfully"
            else:
                self.abort_transaction(transaction_path)
                return "Transaction aborted"
        except Exception as e:
            self.abort_transaction(transaction_path)
            return f"Transaction aborted due to error: {e}"

    def prepare_phase(self, transaction_path):
        queries = self.get_queries(transaction_path)
        participants = self.zk.get_children(f'{transaction_path}/participants')
        results = []
        for participant in participants:
            index = int(participant.split('_')[1])
            if not self.db_enabled[index]:
                continue
            result = self.prepare_participant(transaction_path, participant, index, queries)
            results.append(result)
            if not result:
                return False  # Abort if any prepare fails
        return all(results)

    def prepare_participant(self, transaction_path, participant, index, queries):
        conn = self.db_connections[index]
        try:
            with conn.cursor() as cursor:
                for query in queries:
                    cursor.execute(query)
            self.zk.set(f'{transaction_path}/participants/{participant}', b'READY')
            return True
        except Exception as e:
            conn.rollback()
            return False

    def commit_phase(self, transaction_path):
        participants = self.zk.get_children(f'{transaction_path}/participants')
        results = []
        for participant in participants:
            index = int(participant.split('_')[1])
            if not self.db_enabled[index]:
                continue
            status = self.zk.get(f'{transaction_path}/participants/{participant}')[0]
            if status != b'READY':
                return False
            result = self.commit_participant(transaction_path, participant, index)
            results.append(result)
            if not result:
                return False  # Abort if any commit fails
        success = all(results)
        if success:
            self.zk.set(transaction_path, b'COMMITTED')
        return success

    def commit_participant(self, transaction_path, participant, index):
        conn = self.db_connections[index]
        try:
            conn.commit()
            self.zk.set(f'{transaction_path}/participants/{participant}', b'COMMITTED')
            return True
        except Exception as e:
            conn.rollback()
            return False

    def abort_transaction(self, transaction_path):
        participants = self.zk.get_children(f'{transaction_path}/participants')
        for participant in participants:
            index = int(participant.split('_')[1])
            if not self.db_enabled[index]:
                continue
            conn = self.db_connections[index]
            try:
                conn.rollback()
                self.zk.set(f'{transaction_path}/participants/{participant}', b'ABORTED')
            except Exception as e:
                pass
        self.zk.set(transaction_path, b'ABORTED')

    def get_queries(self, transaction_path):
        queries_path = f'{transaction_path}/queries'
        return [self.zk.get(f'{queries_path}/{node}')[0].decode() for node in self.zk.get_children(queries_path)]

    def cleanup(self):
        for conn in self.db_connections:
            conn.close()
        self.zk.stop()
