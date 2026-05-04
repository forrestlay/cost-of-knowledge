import streamlit as st
import graphviz

label_dict = {
    'ideation': [
        ('Ideation and conception', 'heading'),
        '30 hours',
        'X and Y (2019)'
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

with cost_diagram.subgraph(name='cluster_incubation') as subgraph:
    subgraph.attr(label='Incubation')
    subgraph.attr(labeljust='l')
    subgraph.attr(margin='12')
    subgraph.attr('node', shape='box')
    subgraph.attr('node', penwidth='0')
    subgraph.node('ideation', generate_node_html_label(label_dict['ideation']))
    subgraph.attr('node', penwidth='1')
    subgraph.node('literature-review', 'Literature review')
    subgraph.edge('ideation', 'literature-review')

with cost_diagram.subgraph(name='cluster_data-analysis') as subgraph:
    subgraph.attr(label='Data analysis')
    subgraph.attr(labeljust='l')
    subgraph.attr(margin='12')
    subgraph.node('data-analysis', 'Data analysis')

with cost_diagram.subgraph(name='cluster_writing') as subgraph:
    subgraph.attr(label='Writing')
    subgraph.attr(labeljust='l')
    subgraph.attr(margin='12')
    subgraph.node('writing', 'Writing the publication')

cost_diagram.edge('literature-review', 'data-analysis')
cost_diagram.edge('data-analysis', 'writing')

st.graphviz_chart(cost_diagram, width='stretch')