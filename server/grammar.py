"""A llama.cpp grammar (GBNF) that forces the AI's reply into our edit format.

Small models drift: they answer in prose, re-print code in ```blocks```, or
invent their own markers. With this grammar llama.cpp can only produce:

    PLAN: one line
    <<<<<<< SEARCH
    ...lines...
    =======
    ...lines...
    >>>>>>> REPLACE
    (up to 4 blocks, then it must stop)

or, for an unsafe request, just "PLAN: Let's try a different idea!".

GBNF can't say "any line except =======", so a code line may start with
<, = or > only when the next character is different (`<canvas` and `=>`
are fine; `<<<<<<<` and `=======` are reserved for the markers).
"""

EDIT_GRAMMAR = r"""
root   ::= refuse | plan block block? block? block?
refuse ::= "PLAN: Let's try a different idea!\n"
plan   ::= "PLAN: " [^\n]+ "\n"
block  ::= "<<<<<<< SEARCH\n" line+ "=======\n" line* ">>>>>>> REPLACE\n"
line   ::= text? "\n"
text   ::= [^<=>\n] [^\n]* | "<" ([^<\n] [^\n]*)? | "=" ([^=\n] [^\n]*)? | ">" ([^>\n] [^\n]*)?
"""
