#!/usr/bin/env python3

"""Generates the diagram for the Cost of Knowledge paper.

Copyright 2026 Ben Lay

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import math

import graphviz
import streamlit as st

# Initial variable setup.

st.set_page_config(layout="wide")
st.title("Cost of Knowledge Diagram")

mcr_hourly_wage = 85  # Current default hourly cost

# Helper classes to simplify generating HTML labels for Graphviz and help calculate totals.


class ActivityNode:
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
        hours: float,
        hourly_cost: int,
        hours_calculation: str | None = None,
        cost_calculation: str | None = None,
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
        return math.ceil(self.hours * self.hourly_cost)

    def generate_label_html(self) -> str:
        """
        Generates a HTML label string for the activity node for a Graphviz diagram.
        """
        html_label = '<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0">'
        html_label = (
            html_label + f'<TR><TD ALIGN="CENTER"><B>{self.heading}</B></TD></TR>'
        )

        if self.hours_calculation is not None:
            html_label = (
                html_label
                + f'<TR><TD ALIGN="CENTER">{self.hours_calculation} = {format(self.hours, ",")} hours</TD></TR>'
            )
        else:
            html_label = (
                html_label
                + f'<TR><TD ALIGN="CENTER">{format(self.hours, ",")} hours</TD></TR>'
            )

        if self.cost_calculation is not None:
            html_label = (
                html_label
                + f'<TR><TD ALIGN="CENTER">{self.cost_calculation} = ${format(self.total_cost(), ",")}</TD></TR>'
            )
        else:
            html_label = (
                html_label
                + f'<TR><TD ALIGN="CENTER">{format(self.hours, ",")} hours x ${format(self.hourly_cost, ",")}'
                + f' = ${format(self.total_cost(), ",")}</TD></TR>'
            )

        return html_label + "</TABLE>>"


class CostNode:
    """
    Represents a single research cost centre, for example, databases.

    Attributes:
        heading: Label for the cost.
        cost: Cost in USD.
        cost_calculation: A string providing the equation for calculating total cost.
    """

    def __init__(self, heading: str, cost: int, cost_calculation: str | None = None):
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
        html_label = (
            html_label + f'<TR><TD ALIGN="CENTER"><B>{self.heading}</B></TD></TR>'
        )

        if self.cost_calculation is not None:
            html_label = (
                html_label
                + f'<TR><TD ALIGN="CENTER">{self.cost_calculation} = ${format(self.total_cost(), ",")}</TD></TR>'
            )
        else:
            html_label = (
                html_label
                + f'<TR><TD ALIGN="CENTER">${format(self.total_cost(), ",")}</TD></TR>'
            )

        return html_label + "</TABLE>>"


class TotalNode:
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
        return round(hour_count)

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
        html_label = (
            html_label + f'<TR><TD ALIGN="CENTER"><B>{self.heading}</B></TD></TR>'
        )
        html_label = (
            html_label
            + f'<TR><TD ALIGN="CENTER">{format(self.total_hours(), ",")} hours</TD></TR>'
        )
        html_label = (
            html_label
            + f'<TR><TD ALIGN="CENTER">${format(self.total_cost(), ",")}</TD></TR>'
        )
        return html_label + "</TABLE>>"


# Initialise all of the ActivityNodes and TotalNodes for the graph.

ideation_node = ActivityNode(
    "Ideation and conception",
    55,
    mcr_hourly_wage,
    "33 hrs focal + 22 hrs exploratory",
)

ethics_node = ActivityNode(
    "Ethics approval",
    60,
    mcr_hourly_wage,
    "Midpoint of 25-95 hr range",
)

grants_node = ActivityNode(
    "Grant applications",
    171,
    mcr_hourly_wage,
    "116 primary author hrs + 55 co-author hrs",
)

data_collection_node = ActivityNode(
    heading="Data collection - Interviews and focus groups",
    hours=48.5,
    hourly_cost=mcr_hourly_wage,
    hours_calculation="26 interviews x 111.5 minutes",
)

participant_incentives_node = CostNode(
    heading="Participant incentivisation",
    cost=352,
    cost_calculation="48.5 participant-hrs x $7.25",
)

interview_transcription_node = ActivityNode(
    heading="Transcription verification",
    hours=60.5,
    hourly_cost=mcr_hourly_wage,
    hours_calculation="48.5 interview hrs x 75 min/hr",
)

data_analysis_node = ActivityNode(
    heading="Data analysis",
    hours=157.5,
    hourly_cost=mcr_hourly_wage,
    hours_calculation="Midpoint of 51.5 (rapid analysis) and 266.5 (thematic analysis) hrs",
)

manu_prep_node = ActivityNode(
    "Writing and manuscript preparation", 100, mcr_hourly_wage
)

conferencing_labour_node = ActivityNode(
    "Conferencing (labour)",
    123,
    mcr_hourly_wage,
    "3 events x 41 hrs/event",
)

conferencing_direct_node = CostNode(
    "Conferencing (direct costs)",
    3400,
    "$100 local + $1,000 national + $2,300 international",
)

conferencing_node = TotalNode(
    "Conferencing (total)", [conferencing_labour_node, conferencing_direct_node]
)

peer_review_node = ActivityNode(
    "Peer review",
    9,
    mcr_hourly_wage,
    "3.5 completed reviews, 4 hrs first review/2 hrs re-review",
)

editing_node = ActivityNode("Journal editorial work", 15, mcr_hourly_wage)

overall_total_node = TotalNode(
    "Total cost of a journal publication",
    [
        ideation_node,
        ethics_node,
        grants_node,
        data_collection_node,
        participant_incentives_node,
        interview_transcription_node,
        data_analysis_node,
        manu_prep_node,
        conferencing_labour_node,
        conferencing_direct_node,
        peer_review_node,
        editing_node,
    ],
)

# Graphviz directed graph

cost_diagram = graphviz.Digraph(
    "research-activity-cost", comment="Cost of research activities"
)

cost_diagram.attr("node", shape="box")
cost_diagram.attr(ranksep="0.3")
cost_diagram.attr(newrank="true")

with cost_diagram.subgraph(name="cluster_incubation") as subgraph:  # type: ignore[union-attr]
    subgraph.attr(label="Incubation")
    subgraph.attr(labeljust="l")
    subgraph.attr(margin="12")
    subgraph.attr("node", shape="box")
    subgraph.attr("node", penwidth="0")
    subgraph.node("ideation", ideation_node.generate_label_html())
    subgraph.node("ethics", ethics_node.generate_label_html())
    subgraph.node("grants", grants_node.generate_label_html())
    subgraph.attr("node", penwidth="1")
    subgraph.edge("ideation", "grants")
    subgraph.edge("ideation", "ethics")
    subgraph.edge("grants", "ethics")

with cost_diagram.subgraph(name="cluster_data-analysis") as subgraph:  # type: ignore[union-attr]
    subgraph.attr(label="Data analysis")
    subgraph.attr(labeljust="l")
    subgraph.attr(margin="12")
    subgraph.attr("node", shape="box")
    subgraph.attr("node", penwidth="0")
    subgraph.node("data-collection", data_collection_node.generate_label_html())
    subgraph.node(
        "participant-incentive", participant_incentives_node.generate_label_html()
    )
    subgraph.node(
        "interview-transcription", interview_transcription_node.generate_label_html()
    )
    subgraph.node("data-analysis", data_analysis_node.generate_label_html())
    subgraph.attr("node", penwidth="1")
    subgraph.edge("participant-incentive", "data-collection", None, color="blue")
    subgraph.edge("data-collection", "interview-transcription")
    subgraph.edge("interview-transcription", "data-analysis")

with cost_diagram.subgraph(name="cluster_writing") as subgraph:  # type: ignore[union-attr]
    subgraph.attr(label="Writing")
    subgraph.attr(labeljust="l")
    subgraph.attr(margin="12")
    subgraph.attr("node", shape="box")
    subgraph.attr("node", penwidth="0")
    subgraph.node("writing", manu_prep_node.generate_label_html())
    subgraph.node("conferences", conferencing_node.generate_label_html())
    subgraph.node("conference-labour", conferencing_labour_node.generate_label_html())
    subgraph.node("conference-costs", conferencing_direct_node.generate_label_html())
    subgraph.edge("conference-labour", "conferences", None, color="blue")
    subgraph.edge("conference-costs", "conferences", None, color="blue")
    subgraph.edge("conferences", "writing")
    subgraph.edge("writing", "conferences")

with cost_diagram.subgraph(name="cluster_editing") as subgraph:  # type: ignore[union-attr]
    subgraph.attr(label="Peer review and editing")
    subgraph.attr(labeljust="l")
    subgraph.attr(margin="12")
    subgraph.attr("node", shape="box")
    subgraph.attr("node", penwidth="0")
    subgraph.node("peer-review", peer_review_node.generate_label_html())
    subgraph.node("editing", editing_node.generate_label_html())
    subgraph.edge("peer-review", "editing")
    subgraph.edge("editing", "peer-review")

cost_diagram.node("total", overall_total_node.generate_label_html())

cost_diagram.edge("ethics", "data-collection", None, rank="sink")
cost_diagram.edge("data-analysis", "writing")
cost_diagram.edge("writing", "ideation", None, color="red")
cost_diagram.edge("writing", "data-collection", None, color="red")
cost_diagram.edge("writing", "data-analysis", None, color="red")
cost_diagram.edge("writing", "editing")
cost_diagram.edge("editing", "writing", None, color="red")
cost_diagram.edge("editing", "total")

cost_diagram.attr(
    label=r"*Red arrows represent potential moves between phases arising from revisions and iterations. "
    r"Costs of revision and iteration cycles have not been incorporated unless explicitly stated."
)

st.graphviz_chart(cost_diagram, width="stretch")
st.download_button(
    "Export diagram.dot", cost_diagram.source, file_name="cost_of_knowledge.dot"
)
