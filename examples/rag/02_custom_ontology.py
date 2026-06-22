"""Custom ontology: constrain extraction to your own entity types.

The default ontology ships generic types (Person, Organization, Location,
Concept, Product, Event). For a focused corpus you almost always get better
extraction by handing the LLM a *tuned* vocabulary that matches your domain.

WHY a tuned ontology improves extraction
----------------------------------------
The extractor receives ``ontology.entity_types()`` as the allowed set and is
asked to classify each entity into one of them. A domain-specific vocabulary:

* removes ambiguity — a "framework" is tagged ``Technology``, not the vague
  ``Concept`` or ``Product`` the generic ontology would force it into;
* suppresses noise — types absent from the list are not invited, so the model
  stops inventing off-topic categories;
* yields a cleaner graph — downstream ``type`` filters and graph expansion line
  up with the concepts you actually care about, improving retrieval precision.

This example models a small software-project domain: Person, Project,
Technology, Concept.

Prerequisites: same as ``01_quickstart.py`` (a local FalkorDB on
``localhost:6379`` and ``OPENAI_API_KEY`` / Ollama configured in ``.env``).

Run it::

    uv run python examples/rag/02_custom_ontology.py
"""
# ruff: noqa: T201 - example scripts print their results for the reader.

from __future__ import annotations

from dotenv import load_dotenv

from runic.ogm.driver.factory import create_driver
from runic.rag import Entity, GraphRAG, Ontology, RagSettings

# A short multi-entity text spanning all four custom types.
_DOC = """\
Guido van Rossum created the Python programming language. The Django web
framework is written in Python and powers the Instagram backend. Django
popularised the model-view-template pattern for building web applications.
"""


# 1. Declare custom entity subtypes by subclassing the OGM ``Entity`` model.
#    The class keywords route through the Node metaclass: labels=["Entity", T]
#    keeps every subtype under the shared "Entity" label (so the base schema and
#    indexes still apply), while primary_label="Entity" keeps one primary key.
class Person(Entity, labels=["Entity", "Person"], primary_label="Entity"):
    """A person, e.g. a creator or contributor."""


class Project(Entity, labels=["Entity", "Project"], primary_label="Entity"):
    """A software project, library, or framework."""


class Technology(Entity, labels=["Entity", "Technology"], primary_label="Entity"):
    """A language, runtime, or platform."""


class Concept(Entity, labels=["Entity", "Concept"], primary_label="Entity"):
    """A pattern, methodology, or abstract idea."""


def build_ontology_from_models() -> Ontology:
    """Build the ontology from explicit Entity subclasses (full control)."""
    # Passing model classes lets you attach extra fields/indexes per subtype.
    return Ontology(entity_models=[Person, Project, Technology, Concept])


def build_ontology_from_types() -> Ontology:
    """Build the same vocabulary from plain type names (no class boilerplate).

    ``from_types`` reuses built-in subtypes when a name matches (Person,
    Concept) and dynamically generates the rest (Project, Technology) via the
    same metaclass machinery used above.
    """
    return Ontology.from_types(["Person", "Project", "Technology", "Concept"])


def main() -> None:
    """Ingest a multi-entity text under a custom, domain-tuned ontology."""
    load_dotenv()

    # Both builders yield an equivalent type vocabulary — pick whichever fits.
    ontology = build_ontology_from_models()
    print("Custom ontology types:", ontology.entity_types())
    print("Equivalent from_types:", build_ontology_from_types().entity_types())

    settings = RagSettings(falkordb_graph="rag_custom_ontology")
    driver = create_driver(
        "falkordb",
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        graph=settings.falkordb_graph,
    )

    # Hand the custom ontology to the facade: it is used BOTH to bootstrap the
    # schema (subtype labels + indexes) and to constrain extraction.
    rag = GraphRAG.with_defaults(driver, settings=settings, ontology=ontology)
    rag.bootstrap_schema()

    # The extractor now only classifies entities into Person / Project /
    # Technology / Concept — it will not emit Organization, Location, etc.
    report = rag.ingest_text(_DOC, source="software-domain-demo")
    print(
        f"\nIngested: {report.chunks} chunks, {report.entities} entities, "
        f"{report.relations} relations"
    )

    answer = rag.query("Which technologies and frameworks are described?")
    print("\nAnswer:\n", answer.text)
    print("\nCitations:")
    for citation in answer.citations:
        print(f"  - [{citation.source}] {citation.text[:80]}...")


if __name__ == "__main__":
    main()
