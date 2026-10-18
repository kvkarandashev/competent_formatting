"""Strip revision markup from LaTeX source.

Revision markup comes in two shapes and both have to go: **macros**
(``\\rev{text}``) and **environments** (``\\begin{revblock} ... \\end{revblock}``).
Each can be *opened* (the markup goes, the content stays) or *removed* (both go), and the
``\\newcommand``/``\\newenvironment`` that defines a stripped name is dropped as well, so the
cleaned source does not reference something it no longer defines.

The walk is over ``pylatexenc`` nodes rather than regexes: ``\\rev{a \\emph{b} c}`` needs real
brace matching, and a macro the parser does not know (``\\rev`` is not in any package it has a
spec for) arrives with an empty argument list, with its group following as a sibling node --
which is why an unknown special macro consumes the *next* node instead of its own argument.
"""

from pylatexenc.latexwalker import (
    LatexCharsNode,
    LatexEnvironmentNode,
    LatexGroupNode,
    LatexMacroNode,
    LatexWalker,
)

MACRO_DEFINITIONS = ("newcommand", "renewcommand", "providecommand")
ENVIRONMENT_DEFINITIONS = ("newenvironment", "renewenvironment")


def str_merge(str_list):
    return "".join(str_list)


class IncompleteSpecialMacro(Exception):
    pass


def filter_nodes(nodelist):
    return sorted([n for n in nodelist if n is not None], key=lambda n: n.pos)


def argnlist_of(node):
    """The node's own arguments, or ``[]`` when the parser recorded none."""
    nodeargd = getattr(node, "nodeargd", None)
    if nodeargd is None:
        return []
    return nodeargd.argnlist or []


def defined_name(node):
    """The macro or environment name a definition defines, or ``None``.

    ``\\newcommand{\\rev}[1]{...}`` wraps the name in a group holding a macro node, while
    ``\\newenvironment{revblock}{...}{...}`` wraps a plain chars node; ``\\newcommand\\rev{...}``
    skips the group altogether. All three are in the wild, so none of them may raise.
    """
    arguments = filter_nodes(argnlist_of(node))
    if not arguments:
        return None
    first = arguments[0]
    if isinstance(first, LatexGroupNode):
        inner = filter_nodes(first.nodelist)
        if not inner:
            return None
        first = inner[0]
    if isinstance(first, LatexMacroNode):
        return first.macroname
    if isinstance(first, LatexCharsNode):
        return first.chars.strip() or None
    return None


class ProcessedNodeIterator:
    def __init__(
        self,
        nodes,
        removed_fields=[],
        opened_fields=[],
        removed_envs=[],
        opened_envs=[],
        log_list=None,
    ):
        self.nodes = nodes
        self.current_node_id = 0
        self.removed_fields = set(removed_fields)
        self.opened_fields = set(opened_fields)
        self.removed_envs = set(removed_envs)
        self.opened_envs = set(opened_envs)
        if log_list is None:
            log_list = []
        self.log_list = log_list
        self.command_definitions = set(MACRO_DEFINITIONS)
        self.environment_definitions = set(ENVIRONMENT_DEFINITIONS)

    def is_command_definition(self, macroname):
        return macroname in self.command_definitions

    def is_environment_definition(self, macroname):
        return macroname in self.environment_definitions

    def is_removed_field(self, macroname):
        return macroname in self.removed_fields

    def is_special_field(self, macroname):
        return self.is_removed_field(macroname) or macroname in self.opened_fields

    def is_removed_env(self, environmentname):
        return environmentname in self.removed_envs

    def is_special_env(self, environmentname):
        return self.is_removed_env(environmentname) or environmentname in self.opened_envs

    def child_iterator(self, nodes):
        return ProcessedNodeIterator(
            nodes,
            removed_fields=self.removed_fields,
            opened_fields=self.opened_fields,
            removed_envs=self.removed_envs,
            opened_envs=self.opened_envs,
            log_list=self.log_list,
        )

    def get_full_str(self):
        return str_merge(self)

    def get_full_child_str(self, nodes):
        return self.child_iterator(filter_nodes(nodes)).get_full_str()

    def get_bracketed_full_child_str(self, parent_node, child_nodes, unbracket=False):
        output = self.get_full_child_str(child_nodes)
        if (
            hasattr(parent_node, "delimiters")
            and parent_node.delimiters is not None
            and not unbracket
        ):
            delims = parent_node.delimiters
            output = delims[0] + output + delims[1]
        return output

    def __iter__(self):
        return self

    def get_full_log_error(self, extra_str):
        return str_merge(self.log_list) + "\n" + extra_str

    def raise_incomplete_special_macro_exception(self, extra_str):
        raise IncompleteSpecialMacro(self.get_full_log_error(extra_str))

    def log_str(self, log_str):
        self.log_list.append(log_str)

    def processed_definition(self, current_node, defines_environment=False):
        """Drop a definition of a stripped name, keep every other definition verbatim."""
        name = defined_name(current_node)
        if name is None:
            return current_node.latex_verbatim()
        is_special = self.is_special_env if defines_environment else self.is_special_field
        if is_special(name):
            return ""
        return current_node.latex_verbatim()

    def processed_environment(self, current_node):
        environmentname = current_node.environmentname
        if self.is_removed_env(environmentname):
            return ""
        if environmentname in self.opened_envs:
            # Only the body: \begin/\end go, and so do the environment's own arguments --
            # \begin{revblock}[opt] has no meaning once the environment itself is gone.
            return self.get_full_child_str(current_node.nodelist)
        brenvname = "{" + environmentname + "}"
        return (
            "\\begin"
            + brenvname
            + self.get_full_child_str(current_node.nodelist + argnlist_of(current_node))
            + "\\end"
            + brenvname
        )

    def get_next(self, previous_group_env=None, unbracket=False):
        if self.current_node_id == len(self.nodes):
            if previous_group_env is not None:
                self.raise_incomplete_special_macro_exception(
                    f"Check for incomplete {previous_group_env} instances."
                )
            raise StopIteration
        current_node = self.nodes[self.current_node_id]
        self.current_node_id += 1
        output = None
        if isinstance(current_node, LatexEnvironmentNode):
            output = self.processed_environment(current_node)
        if isinstance(current_node, LatexMacroNode):
            child_nodes = argnlist_of(current_node)
            macroname = current_node.macroname
            if self.is_command_definition(macroname):
                return self.processed_definition(current_node)
            if self.is_environment_definition(macroname):
                return self.processed_definition(current_node, defines_environment=True)
            if self.is_special_field(macroname):
                if len(child_nodes) == 0:
                    contents = self.get_next(previous_group_env=macroname, unbracket=True)
                else:
                    assert len(child_nodes) == 1
                    contents = self.get_bracketed_full_child_str(
                        current_node, child_nodes, unbracket=True
                    )
                if self.is_removed_field(macroname):
                    return ""
                return contents
            output = "\\" + macroname
            if len(child_nodes) != 0:
                output += self.get_bracketed_full_child_str(current_node, child_nodes)
            output += current_node.macro_post_space
        if isinstance(current_node, LatexGroupNode):
            output = self.get_bracketed_full_child_str(
                current_node, current_node.nodelist, unbracket=unbracket
            )

        if output is None:
            output = current_node.latex_verbatim()
            self.log_str(output)
        return output

    def __next__(self):
        next_str = self.get_next()
        self.log_list.append(next_str)
        return next_str


def remove_macros(latex_str, **kwargs):
    """Strip the declared macros and environments from one LaTeX source string.

    Keyword arguments: ``opened_fields``/``removed_fields`` for macros,
    ``opened_envs``/``removed_envs`` for environments.
    """
    nodes, _, _ = LatexWalker(latex_str).get_latex_nodes()
    return ProcessedNodeIterator(nodes, **kwargs).get_full_str()
