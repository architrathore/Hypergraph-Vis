from flask import render_template, request, url_for, jsonify, redirect, Response, send_from_directory
from app import app
from app import APP_STATIC
from app import APP_ROOT
import json
import numpy as np
import pandas as pd
import hypernetx as hnx
import re
import matplotlib.pyplot as plt
import networkx as nx
from tqdm import tqdm
from os import path


def process_graph_edges(edge_str: str):
    """
    Convert a string representation of the hypergraph into a python dictionary

    :param edge_str: string representation of the hypergraph
    :type edge_str: str
    :return: dictionary representing the hypergraph
    :rtype: dict
    """

    edge_str = edge_str.strip().replace('\'', '\"')
    converted_edge_str = edge_str[1:-1].replace('{', '[').replace('}', ']')
    return json.loads('{' + converted_edge_str + '}')

def process_hypergraph(hyper_data: str):
    """
    Returns hgraph, label dict
    """
    hgraph = {}
    label2id = {}
    he_id = 0
    v_id = 0
    for line in hyper_data.split("\n"):
        line = line.rstrip().rsplit(',')

        hyperedge, vertices = line[0], line[1:]
        if hyperedge not in label2id.keys():
            hyperedge_label = re.sub('[\'\s]+', '', hyperedge)
            new_id = 'he'+str(he_id)
            he_id += 1
            label2id[hyperedge_label] = new_id
            hyperedge = new_id
        vertices_new = []
        for v in vertices:
            v_label = re.sub('[\'\s]+', '', v)
            if v_label not in label2id.keys():
                new_id = 'v'+str(v_id)
                v_id += 1
                label2id[v_label] = new_id
                vertices_new.append(new_id)
            else:
                vertices_new.append(label2id[v_label])
        vertices = vertices_new

        if hyperedge not in hgraph.keys():
            hgraph[hyperedge] = vertices
        else:
            hgraph[hyperedge] += vertices
    id2label = {ID:label for label, ID in label2id.items()}

    return hnx.Hypergraph(hgraph), id2label

    # hgraphs = []
    
    # # Separate the hypergraphs based on this regex:
    # # newline followed by one or more whitespace followed by newline
    # file_contents = re.split(r'\n\s+\n', hyper_data)
    
    # num_hgraphs = len(file_contents)
    
    # for i in tqdm(range(0, num_hgraphs)):
    #     # The name and graph are separated by '='
    #     graph_name, graph_dict = file_contents[i].split('=')
    #     graph_dict = process_graph_edges(graph_dict)
    #     # hgraphs.append({'graph_dict':graph_dict, 'graph_name':graph_name})
    #     hgraphs.append(hnx.Hypergraph(graph_dict, name=graph_name))
    # # print(hgraphs)
    
    # return hgraphs[0]


def process_hypergraph_from_csv(graph_file: str):
    hgraph = {}

    with open(graph_file, 'r') as gfile:
        for line in gfile:
            line = line.rstrip().rsplit(',')
            hyperedge, vertices = line[0], line[1:]

            if hyperedge not in hgraph.keys():
                hgraph[hyperedge] = vertices
            else:
                hgraph[hyperedge] += vertices
    return hgraph


def convert_to_line_graph(hgraph_dict, s=1):
    # Line-graph is a NetworkX graph
    line_graph = nx.Graph()

    # Nodes of the line-graph are nodes of the dual graph
    # OR equivalently edges of the original hypergraph
    [line_graph.add_node(edge, vertices=list(vertices)) for edge, vertices in hgraph_dict.items()]

    node_list = list(hgraph_dict.keys())
    vertices_list = []

    non_singletons = []
    non_singleton_vertices = []

    # For all pairs of edges (e1, e2), add edges such that
    # intersection(e1, e2) is not empty
    for node_idx_1, node1 in enumerate(node_list):
        for node_idx_2, node2 in enumerate(node_list[node_idx_1 + 1:]):
            vertices1 = hgraph_dict[node1]
            vertices2 = hgraph_dict[node2]
            # print(vertices1)
            vertices_list += (list(set(vertices1)) + list(set(vertices2)))
            # Compute the intersection size
            intersection_size = len(set(vertices1) & set(vertices2))
            # union_size = len(set(vertices1))
            if intersection_size >= s:
                # print(intersection_size)
                line_graph.add_edge(node1, node2, intersection_size=str(intersection_size))
                non_singletons.append(node1)
                non_singletons.append(node2)
                non_singletons += (list(set(vertices1)) + list(set(vertices2)))
    vertices_list = list(set(vertices_list))
    non_singletons = list(set(non_singletons))
    singletons = [v for v in (node_list + vertices_list) if v not in non_singletons]
    line_graph = nx.readwrite.json_graph.node_link_data(line_graph)
    line_graph['singletons'] = singletons
    return line_graph

def compute_dual_line_graph(hypergraph, s=1):
    dual_hgraph = hypergraph.dual()
    dual_line_graph = convert_to_line_graph(dual_hgraph.incidence_dict, s)
    return dual_line_graph

def assign_hgraph_singletons(hgraph, singletons):
    for node in hgraph['nodes']:
        if node['id'] in singletons:
            node['if_singleton'] = True
        else:
            node['if_singleton'] = False

def find_cc_index(components, vertex_id):
    for i in range(len(components)):
        if vertex_id in components[i]:
            return i

def compute_barcode(graph_data):
    """
    Get barcode of the input linegraph by computing its minimum spanning tree
    """
    nodes = graph_data['nodes']
    links = graph_data['links']
    components = []
    barcode = []
    for node in nodes:
        components.append([node['id']])
    for link in links:
        link['intersection_size'] = int(link['intersection_size'])
    links = sorted(links, key=lambda item: 1 / item['intersection_size'])
    for link in links:
        source_id = link['source']
        target_id = link['target']
        weight = 1 / link['intersection_size']
        source_cc_idx = find_cc_index(components, source_id)
        target_cc_idx = find_cc_index(components, target_id)
        if source_cc_idx != target_cc_idx:
            source_cc = components[source_cc_idx]
            target_cc = components[target_cc_idx]
            components = [components[i] for i in range(len(components)) if i not in [source_cc_idx, target_cc_idx]]
            components.append(source_cc + target_cc)
            link['nodes_subsets'] = {"source_cc": source_cc, "target_cc": target_cc}
            link['cc_list'] = components.copy()
            barcode.append({'birth': 0, 'death': weight, 'edge': link})
    # In the end, there might be more than one independent connected components with death=Infinite 
    for cc in components: 
        barcode.append({'birth': 0, 'death': -1, 'edge': 'undefined'})
    return barcode

def write_json_file(json_dict, path):
    # Write to a json file
    with open(path, 'w') as f:
        f.write(json.dumps(json_dict, indent=4))

# def write_barcode(barcode, path):
#     with open(path, 'w') as f:
#         f.write(json.dumps(barcode, indent=4))

@app.route('/')
@app.route('/Hypergraph-Vis-app')
def index():
    return render_template('HyperVis.html')


@app.route('/import', methods=['POST', 'GET'])
def import_file():
    jsdata = request.get_data().decode('utf-8')
    if jsdata == "hypergraph_samples":
        with open(path.join(APP_STATIC, "uploads/DNS_hypergraph_samples_new.txt"), 'r') as f:
            jsdata = f.read()
        f.close()
    with open(path.join(APP_STATIC, "uploads/current_hypergraph.txt"), 'w') as f:
        f.write(jsdata)
    f.close()
    hgraph, id2label = process_hypergraph(jsdata)
    lgraph = convert_to_line_graph(hgraph.incidence_dict)
    dual_lgraph = compute_dual_line_graph(hgraph)
    hgraph_dict = {hkey:list(vertices) for hkey, vertices in hgraph.incidence_dict.items()}
    write_json_file(hgraph_dict, path.join(APP_STATIC,"uploads/current_hypergraph.json"))
    hgraph = nx.readwrite.json_graph.node_link_data(hgraph.bipartite())
    barcode = compute_barcode(lgraph)
    dual_barcode = compute_barcode(dual_lgraph)

    assign_hgraph_singletons(hgraph, lgraph['singletons'])

    write_json_file(lgraph, path.join(APP_STATIC,"uploads/current_linegraph.json"))
    write_json_file(dual_lgraph, path.join(APP_STATIC,"uploads/current_dual_linegraph.json"))
    write_json_file(barcode, path.join(APP_STATIC,"uploads/current_barcode.json"))
    write_json_file(dual_barcode, path.join(APP_STATIC,"uploads/current_dual_barcode.json"))
    write_json_file(id2label, path.join(APP_STATIC,"uploads/current_labels.json"))

    return jsonify(hyper_data=hgraph, line_data=lgraph, barcode_data=barcode, labels=id2label)


@app.route('/expanded_hgraph', methods=['POST', 'GET'])
def compute_expanded_hgraph():
    jsdata = json.loads(request.get_data())
    print(jsdata)
    variant = jsdata['variant']
    hyper_data = jsdata['cc_dict']
    source_id = jsdata['edge']['source']
    target_id = jsdata['edge']['target']
    source_cc = jsdata['edge']['nodes_subsets']['source_cc']
    target_cc = jsdata['edge']['nodes_subsets']['target_cc']
    hyperedges2vertices = jsdata['hyperedges2vertices']
    for cc_key in hyper_data:
        hyperedge_keys = cc_key.split("|")
        hyperedge_keys.pop()
        if all(h1 in hyperedge_keys for h1 in source_cc) and all(h2 in hyperedge_keys for h2 in target_cc): # if source_cc and target_cc are combined
            print(hyperedge_keys, source_cc, target_cc)
            cc1_id_list = source_cc
            cc2_id_list = [he for he in hyperedge_keys if he not in cc1_id_list]
            cc1_id = ""
            cc2_id = ""
            for he in cc1_id_list:
                cc1_id += he + "|"
            for he in cc2_id_list:
                cc2_id += he + "|"
            cc1 = []
            cc2 = []
            for he in cc1_id_list:
                for v in hyperedges2vertices[he]:
                    if v not in cc1:
                        cc1.append(v)
            for he in cc2_id_list:
                for v in hyperedges2vertices[he]:
                    if v not in cc2:
                        cc2.append(v)
            del hyper_data[cc_key]
            hyper_data[cc1_id] = cc1
            hyper_data[cc2_id] = cc2
            break
    hgraph = hnx.Hypergraph(hyper_data)
    if variant == "Dual Line Graph":
        hgraph = hgraph.dual()
    hgraph = nx.readwrite.json_graph.node_link_data(hgraph.bipartite())
    return jsonify(hyper_data=hgraph, cc_dict=hyper_data)

@app.route('/simplified_hgraph', methods=['POST', 'GET'])
def compute_simplified_hgraph():
    jsdata = json.loads(request.get_data())
    variant = jsdata['variant']
    hyper_data = jsdata['cc_dict']
    hgraph = hnx.Hypergraph(hyper_data)
    if variant == "Dual Line Graph":
        hgraph = hgraph.dual()
    hgraph = nx.readwrite.json_graph.node_link_data(hgraph.bipartite())
    return jsonify(hyper_data=hgraph)

@app.route('/switch_line_variant', methods=['POST', 'GET'])
def switch_line_variant():
    variant = request.get_data().decode('utf-8')
    if variant == "Original Line Graph":
        filename = ""
    elif variant == "Dual Line Graph":
        filename = "_dual"
    with open(path.join(APP_STATIC,"uploads/current"+filename+"_linegraph.json")) as f:
        lgraph = json.load(f)
    with open(path.join(APP_STATIC,"uploads/current"+filename+"_barcode.json")) as f:
        barcode = json.load(f)
    with open(path.join(APP_STATIC,"uploads/current_hypergraph.json")) as f:
        hgraph = json.load(f)
    hgraph = nx.readwrite.json_graph.node_link_data(hnx.Hypergraph(hgraph).bipartite())
    assign_hgraph_singletons(hgraph, lgraph['singletons'])
    return jsonify(hyper_data=hgraph, line_data=lgraph, barcode_data=barcode)

@app.route('/change_s_value', methods=['POST', 'GET'])
def recompute():
    """
    Given an s value, recompute the line graph and the barcode.
    """
    jsdata = json.loads(request.get_data())
    s = int(jsdata['s'])
    variant = jsdata['variant']
    with open(path.join(APP_STATIC, "uploads/current_hypergraph.json"), 'r') as f:
        hgraph_dict = json.load(f)
    hgraph = hnx.Hypergraph(hgraph_dict)
    lgraph = convert_to_line_graph(hgraph.incidence_dict, s=s)
    dual_lgraph = compute_dual_line_graph(hgraph, s=s)
    hgraph = nx.readwrite.json_graph.node_link_data(hgraph.bipartite())
    barcode = compute_barcode(lgraph)
    dual_barcode = compute_barcode(dual_lgraph)
    # print(dual_lgraph['singletons'])

    write_json_file(lgraph, path.join(APP_STATIC,"uploads/current_linegraph.json"))
    write_json_file(dual_lgraph, path.join(APP_STATIC,"uploads/current_dual_linegraph.json"))
    write_json_file(barcode, path.join(APP_STATIC,"uploads/current_barcode.json"))
    write_json_file(dual_barcode, path.join(APP_STATIC,"uploads/current_dual_barcode.json"))
    if variant == "Original Line Graph":
        assign_hgraph_singletons(hgraph, lgraph['singletons'])
        return jsonify(hyper_data=hgraph, line_data=lgraph, barcode_data=barcode)
    else:
        assign_hgraph_singletons(hgraph, dual_lgraph['singletons'])
        return jsonify(hyper_data=hgraph, line_data=dual_lgraph, barcode_data=dual_barcode)
