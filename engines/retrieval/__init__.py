"""Engine C: retrieval and verified answers. The pure part.

Like Engines A and B, this is a library with no web framework, no database,
no network and no model inside it. The API layer (apps/api/app/qa/) does the
I/O: it runs the SQL searches, calls the embedding and reranking models and
Gemini, and hands the results to these functions.

    fusion.reciprocal_rank_fusion   merge the dense and keyword result lists
    language                        script detection, digit and question normalisation
    quantities                      the deterministic number check
    verify                          which answer sentences survive, and the final answer text

The honesty guarantee lives in `quantities` and `verify`: a sentence reaches
the user only if every number in it is in a clause that supports it (or in
the user's own question), and a second model judged that clause to support
the sentence. Nothing here can add a sentence or a number; it can only remove.
"""
