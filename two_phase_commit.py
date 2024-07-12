from kazoo.client import KazooClient
import psycopg

# Initialize two phase commit class for transaction handling
class TwoPhaseCommit:
    # Initialize Zookeeper client and connect to server
    # Connect to postgres DB
    def __init__(self, zk_hosts, db_configs):
        self.zk = KazooClient(hosts=zk_hosts)
        self.zk.start()
        self.db_connections = [psycopg.connect(**config, autocommit=False) for config in db_configs]
# Begin of TPC creating a znode for each participant
    def begin_phase(self, transaction_path):
        participants = self.zk.get_children(f'{transaction_path}/participants')
        results = []
        for i, participant in enumerate(participants):
            results.append(self.begin_participant(transaction_path, participant, i))
        return all(results)
# Set status for a given participant
    def begin_participant(self, transaction_path, participant, index):
        conn = self.db_connections[index]
        try:
            # Start a new transaction
            conn.autocommit = False
            self.zk.set(f'{transaction_path}/participants/{participant}', b'STARTED')
            return True
        except Exception as e:
            return False
# creates a transcation node for each transaction and each node in ZooKeeper
    def create_transaction(self, root_name, transaction_name, queries):
        try:
            self.zk.ensure_path(f'{root_name}')
            transaction_id = len(self.zk.get_children(f'{root_name}'))
            transaction_path = self.zk.create(f'{root_name}/{transaction_name}_{transaction_id}', b'NEW')
            queries_path = self.zk.create(f'{transaction_path}/queries')
            participants_path = self.zk.create(f'{transaction_path}/participants')

            for i, query in enumerate(queries):
                self.zk.create(f'{queries_path}/q_{i}', query.encode())

            for i in range(len(self.db_connections)):
                self.zk.create(f'{participants_path}/P_{i}', b'NEW')

            return transaction_path
        except Exception as e:
            raise
# If all 3 phases passed transaction either commits or aborts on all 3 DBs
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
# Get all participants and queries to prepare
    def prepare_phase(self, transaction_path):
        queries = self.get_queries(transaction_path)
        participants = self.zk.get_children(f'{transaction_path}/participants')

        results = []
        for i, participant in enumerate(participants):
            results.append(self.prepare_participant(transaction_path, participant, i, queries))

        return all(results)
# PRepare a given participant based on index and db connection set zk node to ready
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
# Commit transcation if all participants are ready
    def commit_phase(self, transaction_path):
        participants = self.zk.get_children(f'{transaction_path}/participants')

        if not all(self.zk.get(f'{transaction_path}/participants/{p}')[0] == b'READY' for p in participants):
            return False

        results = []
        for i, participant in enumerate(participants):
            results.append(self.commit_participant(transaction_path, participant, i))

        success = all(results)
        if success:
            self.zk.set(transaction_path, b'COMMITTED')
        return success
# If not all participants are committed roll all databases back
    def commit_participant(self, transaction_path, participant, index):
        conn = self.db_connections[index]
        try:
            conn.commit()
            self.zk.set(f'{transaction_path}/participants/{participant}', b'COMMITTED')
            return True
        except Exception as e:
            conn.rollback()
            return False
# If commit failed set Abort status for each participant
    def abort_transaction(self, transaction_path):
        participants = self.zk.get_children(f'{transaction_path}/participants')
        for i, participant in enumerate(participants):
            conn = self.db_connections[i]
            try:
                conn.rollback()
                self.zk.set(f'{transaction_path}/participants/{participant}', b'ABORTED')
            except Exception as e:
                pass
        self.zk.set(transaction_path, b'ABORTED')
# return the query from znode
    def get_queries(self, transaction_path):
        queries_path = f'{transaction_path}/queries'
        return [self.zk.get(f'{queries_path}/{node}')[0].decode() for node in self.zk.get_children(queries_path)]
# After tpc ended clean all connections
    def cleanup(self):
        for conn in self.db_connections:
            conn.close()
        self.zk.stop()

if __name__ == "__main__":
    zk_hosts = '127.0.0.1:2181'
    db_configs = [
        {'dbname': 'db', 'user': 'user', 'password': 'password', 'host': '127.0.0.1', 'port': '5432'},
        {'dbname': 'db', 'user': 'user', 'password': 'password', 'host': '127.0.0.1', 'port': '5433'},
        {'dbname': 'db', 'user': 'user', 'password': 'password', 'host': '127.0.0.1', 'port': '5434'}
    ]
    queries = [
        '''INSERT INTO accounts (name, id_number, iban, balance) VALUES ('Max Mustermann', '1234', 5678, 340.0)'''
    ]

    tpc = TwoPhaseCommit(zk_hosts, db_configs)
    try:
        #Define Transcation node as T_x and main Root as 'APP'
        transaction_path = tpc.create_transaction('APP', 'T', queries)
        result = tpc.execute_transaction(transaction_path)
        print(result)
    finally:
        tpc.cleanup()
