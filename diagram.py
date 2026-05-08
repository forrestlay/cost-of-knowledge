import streamlit as st
import graphviz

# Initial variable setup.

st.set_page_config(layout="wide")
st.title('Cost of Knowledge Diagram')

mcr_hourly_wage = 83 # Current default hourly cost

# Helper classes to simplify generating HTML labels for Graphviz and help calculate totals.

class ActivityNode():
    """
    Represents a single research activity.

    Attributes:
        heading: Label for the activity.
        hours: Total hours estimated for the activity.
        hourly_cost: Cost in USD per hour of the activity, generally based on a mid-career researcher's hourly wage.
        hours_calculation: A string providing the equation for calculating total hours.
        cost_calculation: A string providing the equation for calculating total cost.
    """
    def __init__(
            self,
            heading: str,
            hours: int,
            hourly_cost: int,
            hours_calculation: str | None = None,
            cost_calculation: str | None = None
    ):
        """
        Initialises the Activity Node.
        
        Args:
            heading: Label for the activity.
            hours: Total hours estimated for the activity.
            hourly_cost: Cost in USD per hour of the activity, generally based on a mid-career researcher's hourly wage.
            hours_calculation: A string providing the equation for calculating total hours.
            cost_calculation: A string providing the equation for calculating total cost.
        """
        self.heading = heading
        self.hours = hours
        self.hourly_cost = hourly_cost
        self.hours_calculation = hours_calculation
        self.cost_calculation = cost_calculation
    
    def total_cost(self) -> int:
        """
        Returns the total cost of the activity, calculated as hours * hourly_cost.
        """
        return self.hours * self.hourly_cost
    
    def generate_label_html(self) -> str:
        """
        Generates a HTML label string for the activity node for a Graphviz diagram.
        """
        html_label = '<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0">'
        html_label = html_label + f'<TR><TD ALIGN="CENTER"><B>{self.heading}</B></TD></TR>'

        if self.hours_calculation is not None:
            html_label = html_label + f'<TR><TD ALIGN="CENTER">{self.hours_calculation} = {format(self.hours, ',')} hours</TD></TR>'
        else:
            html_label = html_label + f'<TR><TD ALIGN="CENTER">{format(self.hours, ',')} hours</TD></TR>'
        
        if self.cost_calculation is not None:
            html_label = html_label + f'<TR><TD ALIGN="CENTER">{self.cost_calculation} = ${format(self.total_cost(), ',')}</TD></TR>'
        else:
            html_label = html_label + f'<TR><TD ALIGN="CENTER">{format(self.hours,',')} hours x ${format(self.hourly_cost, ',')} = ${format(self.total_cost(), ',')}</TD></TR>'

        html_label = html_label + '</TABLE>>'
        return html_label

class CostNode():
    """
    Represents a single research cost centre, for example, databases.

    Attributes:
        heading: Label for the cost.
        cost: Cost in USD.
        cost_calculation: A string providing the equation for calculating total cost.
    """
    def __init__(
            self,
            heading: str,
            cost: int,
            cost_calculation: str | None = None
    ):
        """
        Initialises the Activity Node.
        
        Args:
            heading: Label for the activity.
            cost: Cost in USD.
            cost_calculation: A string providing the equation for calculating total cost.
        """
        self.heading = heading
        self.cost = cost
        self.cost_calculation = cost_calculation
    
    def total_cost(self) -> int:
        """
        Returns the total cost.
        """
        return self.cost
    
    def generate_label_html(self) -> str:
        """
        Generates a HTML label string for the activity node for a Graphviz diagram.
        """
        html_label = '<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0">'
        html_label = html_label + f'<TR><TD ALIGN="CENTER"><B>{self.heading}</B></TD></TR>'
        html_label = html_label + f'<TR><TD ALIGN="CENTER">${format(self.total_cost(), ',')}</TD></TR>'

        if self.cost_calculation is not None:
            html_label = html_label + f'<TR><TD ALIGN="CENTER">{self.cost_calculation}</TD></TR>'

        html_label = html_label + '</TABLE>>'
        return html_label

class TotalNode():
    """
    Calculates total hours and costs for a given set of ActivityNodes and CostNodes.

    Attributes:
        heading: Label for the total node.
        nodes: A list of ActivityNodes and CostNodes from which totals will be calculated.
    """
    def __init__(self, heading: str, nodes: list[ActivityNode | CostNode]):
        """
        Initialises the TotalNode

        Args:
            heading: Label for the total node.
            nodes: A list of ActivityNodes and CostNodes from which totals will be calculated.
        """
        self.heading = heading
        self.nodes = nodes
    
    def total_hours(self) -> int:
        """
        Returns the total number of hours across the nodes in self.nodes.
        """
        hour_count = 0
        for activity in self.nodes:
            if isinstance(activity, ActivityNode):
                hour_count += activity.hours
        return hour_count
    
    def total_cost(self) -> int:
        """
        Returns the total cost across the nodes in self.nodes.
        """
        cost_count = 0
        for activity in self.nodes:
            cost_count += activity.total_cost()
        return cost_count
    
    def generate_label_html(self) -> str:
        """
        Generates a HTML label string for the total node for a Graphviz diagram.
        """
        html_label = '<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0">'
        html_label = html_label + f'<TR><TD ALIGN="CENTER"><B>{self.heading}</B></TD></TR>'
        html_label = html_label + f'<TR><TD ALIGN="CENTER">{format(self.total_hours(), ',')} hours</TD></TR>'
        html_label = html_label + f'<TR><TD ALIGN="CENTER">${format(self.total_cost(), ',')}</TD></TR>'
        html_label = html_label + '</TABLE>>'
        return html_label

# Initialise all of the ActivityNodes and TotalNodes for the graph.

ideation_node = ActivityNode(
    'Ideation and conception',
    6*35+6*8,
    mcr_hourly_wage,
    '6 x 35 hours + 6 x 8 hours'
)

ethics_node = ActivityNode(
    'Ethics approval',
    93,
    mcr_hourly_wage,
    'Median time from estimated range of 45-140 hours'
)

database_node = CostNode(
    'Database access',
    10000,
    'Placeholder number'
)

software_node = CostNode(
    'Software licences',
    5000,
    'Placeholder number'
)

manu_prep_node = ActivityNode(
    'Manuscript preparation and revision',
    100,
    mcr_hourly_wage
)

formatting_node = ActivityNode(
    'Manuscript formatting',
    14,
    mcr_hourly_wage
)

copyediting_node = CostNode(
    'Professional copyediting',
    500
)

conferencing_node = ActivityNode(
    'Conferencing and workshopping',
    40+40+75+3*12,
    mcr_hourly_wage,
    '155 hours author labour + 36 hours third party labour'
)

peer_review_node = ActivityNode(
    'Peer review',
    10*6,
    mcr_hourly_wage,
    '10 reviews x 6 hours'
)

editing_node = ActivityNode(
    'Journal editorial handling',
    3*8,
    mcr_hourly_wage,
    '3 manuscripts x 8 hours'
)

overall_total_node = TotalNode('Total cost of a journal publication',[
    ideation_node,
    ethics_node,
    database_node,
    software_node,
    manu_prep_node,
    conferencing_node,
    copyediting_node,
    peer_review_node,
    editing_node
])

# Graphviz directed graph

cost_diagram = graphviz.Digraph('research-activity-cost', comment='Cost of research activities')

cost_diagram.attr('node', shape='box')
cost_diagram.attr(ranksep='0.7')

with cost_diagram.subgraph(name='cluster_incubation') as subgraph: #type: ignore[union-attr]
    subgraph.attr(label='Incubation')
    subgraph.attr(labeljust='l')
    subgraph.attr(margin='12')
    subgraph.attr('node', shape='box')
    subgraph.attr('node', penwidth='0')
    subgraph.node('ideation', ideation_node.generate_label_html())
    subgraph.node('ethics', ethics_node.generate_label_html())
    subgraph.attr('node', penwidth='1')
    subgraph.node('grants', 'Grant applications')
    subgraph.node('literature-review', 'Literature review')
    subgraph.edge('ideation', 'literature-review')
    subgraph.edge('literature-review', 'grants')
    subgraph.edge('literature-review', 'ethics')
    subgraph.edge('grants', 'ethics')

with cost_diagram.subgraph(name='cluster_data-analysis') as subgraph: #type: ignore[union-attr]
    subgraph.attr(label='Data analysis')
    subgraph.attr(labeljust='l')
    subgraph.attr(margin='12')
    subgraph.attr('node', shape='box')
    subgraph.attr('node', penwidth='0')
    subgraph.node('databases', database_node.generate_label_html())
    subgraph.node('software', software_node.generate_label_html())
    subgraph.attr('node', penwidth='1')
    subgraph.node('data-collection', 'Data collection')
    subgraph.node('data-analysis', 'Data analysis')
    subgraph.edge('data-collection', 'data-analysis')
    subgraph.edge('databases', 'data-analysis')
    subgraph.edge('software', 'data-analysis')

with cost_diagram.subgraph(name='cluster_writing') as subgraph: #type: ignore[union-attr]
    subgraph.attr(label='Writing')
    subgraph.attr(labeljust='l')
    subgraph.attr(margin='12')
    subgraph.attr('node', shape='box')
    subgraph.attr('node', penwidth='0')
    subgraph.node('writing', manu_prep_node.generate_label_html())
    subgraph.node('formatting', formatting_node.generate_label_html())
    subgraph.node('conferences', conferencing_node.generate_label_html())
    subgraph.node('copyediting', copyediting_node.generate_label_html())
    subgraph.edge('formatting', 'writing', 'Included in', color='blue')
    subgraph.edge('conferences', 'writing')
    subgraph.edge('copyediting', 'writing')
    subgraph.edge('writing', 'conferences')

with cost_diagram.subgraph(name='cluster_editing') as subgraph: #type: ignore[union-attr]
    subgraph.attr(label='Peer review and editing')
    subgraph.attr(labeljust='l')
    subgraph.attr(margin='12')
    subgraph.attr('node', shape='box')
    subgraph.attr('node', penwidth='0')
    subgraph.node('peer-review', peer_review_node.generate_label_html())
    subgraph.node('editing', editing_node.generate_label_html())
    subgraph.edge('peer-review', 'editing')
    subgraph.edge('editing', 'peer-review')

cost_diagram.node('total', overall_total_node.generate_label_html())

cost_diagram.edge('ethics', 'data-collection')
cost_diagram.edge('data-analysis', 'writing')
cost_diagram.edge('writing', 'data-collection', None, color='red')
cost_diagram.edge('writing', 'editing')
cost_diagram.edge('editing', 'writing', None, color='red')
cost_diagram.edge('editing', 'total')

st.graphviz_chart(cost_diagram, width='stretch')