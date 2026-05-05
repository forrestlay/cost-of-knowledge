import streamlit as st
import graphviz

total_hours = 258 + 100 + 60 + 24
total_cost = total_hours * 83

label_dict = {
    'ideation': [
        ('Ideation and conception', 'heading'),
        '6 x 35 hours + 6 x 8 hours = 258 hours',
        '258 hours x $83/h = $21,414'
    ],
    'writing': [
        ('Manuscript preparation (total)', 'heading'),
        '100 hours',
        '100 hours x $83/h = $8,300'
    ],
    'formatting': [
        ('Manuscript formatting', 'heading'),
        '14 hours',
        '14 hours x $83/h = $1,162'
    ],
    'peer-review': [
        ('Peer review', 'heading'),
        '10 reviews x 6 hours = 60 hours',
        '60 hours x $83/h = $4,980'
    ],
    'editing': [
        ('Journal editorial handling', 'heading'),
        '3 manuscripts x 8 hours = 24 hours',
        '24 hours x $83/h = $1,992'
    ],
    'total': [
        ('Total cost of a journal publication', 'heading'),
        str(total_hours) + ' hours',
        '$' + str(total_cost)
    ]
}

def generate_node_html_label(text: list[str | tuple[str, str]]) -> str:
    html_label = '<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0">'
    for text_element in text:
        if isinstance(text_element, tuple):
            if text_element[1] == 'heading':
                html_label = html_label + f'<TR><TD ALIGN="CENTER"><B>{text_element[0]}</B></TD></TR>'
            else:
                html_label = html_label + f'<TR><TD ALIGN="CENTER">{text_element[0]}</TD></TR>'
        else:
            html_label = html_label + f'<TR><TD ALIGN="CENTER">{text_element}</TD></TR>'
    html_label = html_label + '</TABLE>>'
    return html_label

cost_diagram = graphviz.Digraph('research-activity-cost', comment='Cost of research activities')

cost_diagram.attr('node', shape='box')

with cost_diagram.subgraph(name='cluster_incubation') as subgraph: #type: ignore[union-attr]
    subgraph.attr(label='Incubation')
    subgraph.attr(labeljust='l')
    subgraph.attr(margin='12')
    subgraph.attr('node', shape='box')
    subgraph.attr('node', penwidth='0')
    subgraph.node('ideation', generate_node_html_label(label_dict['ideation']))
    subgraph.attr('node', penwidth='1')
    subgraph.node('literature-review', 'Literature review')
    subgraph.node('ethics', 'Ethics application')
    subgraph.edge('ideation', 'literature-review')
    subgraph.edge('literature-review', 'ethics')

with cost_diagram.subgraph(name='cluster_data-analysis') as subgraph: #type: ignore[union-attr]
    subgraph.attr(label='Data analysis')
    subgraph.attr(labeljust='l')
    subgraph.attr(margin='12')
    subgraph.attr('node', shape='box')
    subgraph.attr('node', penwidth='1')
    subgraph.node('databases', 'Database access')
    subgraph.node('data-analysis', 'Data analysis')
    subgraph.edge('databases', 'data-analysis')

with cost_diagram.subgraph(name='cluster_writing') as subgraph: #type: ignore[union-attr]
    subgraph.attr(label='Writing')
    subgraph.attr(labeljust='l')
    subgraph.attr(margin='12')
    subgraph.attr('node', penwidth='1')
    subgraph.attr('node', shape='box')
    subgraph.node('writing', generate_node_html_label(label_dict['writing']))
    subgraph.node('formatting', generate_node_html_label(label_dict['formatting']))
    subgraph.node('workshops', 'Workshopping')
    subgraph.node('conferences', 'Conference attendance')
    subgraph.edge('formatting', 'writing')
    subgraph.edge('workshops', 'writing')
    subgraph.edge('conferences', 'writing')

with cost_diagram.subgraph(name='cluster_editing') as subgraph: #type: ignore[union-attr]
    subgraph.attr(label='Peer review and editing')
    subgraph.attr(labeljust='l')
    subgraph.attr(margin='12')
    subgraph.attr('node', penwidth='1')
    subgraph.attr('node', shape='box')
    subgraph.node('peer-review', generate_node_html_label(label_dict['peer-review']))
    subgraph.node('editing', generate_node_html_label(label_dict['editing']))
    subgraph.edge('peer-review', 'editing')
    subgraph.edge('editing', 'peer-review')

cost_diagram.node('total', generate_node_html_label(label_dict['total']))

cost_diagram.edge('ethics', 'data-analysis')
cost_diagram.edge('data-analysis', 'writing')
cost_diagram.edge('writing', 'editing')
cost_diagram.edge('editing', 'total')

st.graphviz_chart(cost_diagram, width='stretch')