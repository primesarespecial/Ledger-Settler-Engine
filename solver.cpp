#include <algorithm>
#include <climits>
#include <iostream>
#include <queue>
#include <utility>
#include <vector>

using namespace std;


struct Edge {
    int to;
    long long cap;
    long long flow;
    int rev;
};


class Dinic {
private:
    int n;

    vector<vector<Edge>> adj;
    vector<int> level;
    vector<int> ptr;

public:
    explicit Dinic(int n)
        : n(n),
          adj(n),
          level(n),
          ptr(n) {}


    int add_edge(
        int from,
        int to,
        long long capacity
    ) {
        int forward_index =
            static_cast<int>(
                adj[from].size()
            );

        Edge forward = {
            to,
            capacity,
            0,
            static_cast<int>(
                adj[to].size()
            )
        };

        Edge reverse = {
            from,
            0,
            0,
            forward_index
        };

        adj[from].push_back(forward);
        adj[to].push_back(reverse);

        return forward_index;
    }


    bool bfs(
        int source,
        int sink
    ) {
        fill(
            level.begin(),
            level.end(),
            -1
        );

        queue<int> q;

        level[source] = 0;
        q.push(source);

        while (!q.empty()) {

            int vertex = q.front();
            q.pop();

            for (const Edge& edge : adj[vertex]) {

                long long residual =
                    edge.cap - edge.flow;

                if (
                    residual > 0 &&
                    level[edge.to] == -1
                ) {
                    level[edge.to] =
                        level[vertex] + 1;

                    q.push(edge.to);
                }
            }
        }

        return level[sink] != -1;
    }


    long long dfs(
        int vertex,
        int sink,
        long long pushed
    ) {
        if (pushed == 0) {
            return 0;
        }

        if (vertex == sink) {
            return pushed;
        }

        for (
            int& edge_id = ptr[vertex];
            edge_id <
                static_cast<int>(
                    adj[vertex].size()
                );
            ++edge_id
        ) {

            Edge& edge =
                adj[vertex][edge_id];

            if (
                level[edge.to] !=
                level[vertex] + 1
            ) {
                continue;
            }

            long long residual =
                edge.cap - edge.flow;

            if (residual <= 0) {
                continue;
            }

            long long amount =
                dfs(
                    edge.to,
                    sink,
                    min(
                        pushed,
                        residual
                    )
                );

            if (amount == 0) {
                continue;
            }

            edge.flow += amount;

            adj[edge.to]
               [edge.rev]
               .flow -= amount;

            return amount;
        }

        return 0;
    }


    long long max_flow(
        int source,
        int sink
    ) {
        long long total_flow = 0;

        while (bfs(source, sink)) {

            fill(
                ptr.begin(),
                ptr.end(),
                0
            );

            while (true) {

                long long pushed =
                    dfs(
                        source,
                        sink,
                        LLONG_MAX
                    );

                if (pushed == 0) {
                    break;
                }

                total_flow += pushed;
            }
        }

        return total_flow;
    }


    long long get_flow(
        int from,
        int edge_index
    ) const {
        return adj[from]
                  [edge_index]
                  .flow;
    }
};


struct OriginalEdge {
    int from;
    int to;
    long long limit;
    int adjacency_index;
};


int main() {

    ios::sync_with_stdio(false);
    cin.tie(nullptr);


    int num_nodes;
    int num_edges;

    if (!(cin >> num_nodes >> num_edges)) {
        cerr << "Could not read N and M\n";
        return 1;
    }


    if (
        num_nodes <= 0 ||
        num_edges < 0
    ) {
        cerr << "Invalid N or M\n";
        return 1;
    }


    /*
     * Nodes:
     *
     * 0 = super source
     *
     * 1 ... N = people
     *
     * N + 1 = super sink
     */

    int source = 0;
    int sink = num_nodes + 1;


    Dinic dinic(
        num_nodes + 2
    );


    vector<long long> balance(
        num_nodes + 1,
        0
    );


    // ----------------------------------------------------
    // Read balances
    // ----------------------------------------------------

    long long total_balance = 0;


    for (
        int node = 1;
        node <= num_nodes;
        ++node
    ) {

        if (!(cin >> balance[node])) {

            cerr
                << "Failed to read balance "
                << "for node "
                << node
                << "\n";

            return 1;
        }

        total_balance +=
            balance[node];
    }


    if (total_balance != 0) {

        cerr
            << "Balances do not sum to zero\n";

        return 1;
    }


    // ----------------------------------------------------
    // Read person-to-person payment limits
    // ----------------------------------------------------

    vector<OriginalEdge> original_edges;

    original_edges.reserve(
        num_edges
    );


    for (
        int i = 0;
        i < num_edges;
        ++i
    ) {

        int from;
        int to;

        long long limit;


        if (!(cin >> from >> to >> limit)) {

            cerr
                << "Could not read edge "
                << i
                << "\n";

            return 1;
        }


        if (
            from < 1 ||
            from > num_nodes ||
            to < 1 ||
            to > num_nodes
        ) {

            cerr
                << "Invalid node in edge "
                << i
                << "\n";

            return 1;
        }


        if (from == to) {

            cerr
                << "Self edges are not allowed\n";

            return 1;
        }


        if (limit < 0) {

            cerr
                << "Negative limit in edge "
                << i
                << "\n";

            return 1;
        }


        int edge_index =
            dinic.add_edge(
                from,
                to,
                limit
            );


        original_edges.push_back({
            from,
            to,
            limit,
            edge_index
        });
    }


    // ----------------------------------------------------
    // Attach super source and super sink
    //
    // balance < 0:
    // person must SEND money
    //
    // source -> person
    //
    // balance > 0:
    // person must RECEIVE money
    //
    // person -> sink
    // ----------------------------------------------------

    long long required_flow = 0;


    for (
        int node = 1;
        node <= num_nodes;
        ++node
    ) {

        if (balance[node] < 0) {

            dinic.add_edge(
                source,
                node,
                -balance[node]
            );

        } else if (balance[node] > 0) {

            dinic.add_edge(
                node,
                sink,
                balance[node]
            );

            required_flow +=
                balance[node];
        }
    }


    // ----------------------------------------------------
    // Run max-flow
    // ----------------------------------------------------

    long long max_flow =
        dinic.max_flow(
            source,
            sink
        );


    // ----------------------------------------------------
    // If max flow cannot satisfy every positive balance,
    // a complete settlement does not exist.
    // ----------------------------------------------------

    if (max_flow != required_flow) {

        cout
            << "NOT_POSSIBLE "
            << max_flow
            << " "
            << required_flow
            << "\n";

        return 0;
    }


    // ----------------------------------------------------
    // Extract actual payment instructions
    // ----------------------------------------------------

    vector<pair<int, long long>>
        assignments;


    for (
        int i = 0;
        i <
            static_cast<int>(
                original_edges.size()
            );
        ++i
    ) {

        const OriginalEdge& edge =
            original_edges[i];


        long long flow =
            dinic.get_flow(
                edge.from,
                edge.adjacency_index
            );


        if (flow > 0) {

            assignments.push_back({
                i,
                flow
            });
        }
    }


    // ----------------------------------------------------
    // Output
    // ----------------------------------------------------

    cout
        << "POSSIBLE "
        << required_flow
        << "\n";


    cout
        << "ASSIGNMENTS "
        << assignments.size()
        << "\n";


    for (
        const auto& assignment :
        assignments
    ) {

        cout
            << assignment.first
            << " "
            << assignment.second
            << "\n";
    }


    return 0;
}