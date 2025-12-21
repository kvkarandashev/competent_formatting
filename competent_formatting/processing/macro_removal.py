from pylatexenc.latexwalker import (
    LatexEnvironmentNode,
    LatexGroupNode,
    LatexMacroNode,
    LatexWalker,
)


def str_merge(str_list):
    return "".join(str_list)


class IncompleteSpecialMacro(Exception):
    pass


def filter_nodes(nodelist):
    return sorted([n for n in nodelist if n is not None], key=lambda n: n.pos)


class ProcessedNodeIterator:
    def __init__(self, nodes, removed_fields=[], opened_fields=[], log_list=None):
        self.nodes = nodes
        self.current_node_id = 0
        self.removed_fields = set(removed_fields)
        self.opened_fields = set(opened_fields)
        if log_list is None:
            log_list = []
        self.log_list = log_list
        self.command_definitions = set(["renewcommand", "newcommand"])

    def is_command_definition(self, macroname):
        return macroname in self.command_definitions

    def is_removed_field(self, macroname):
        return macroname in self.removed_fields

    def is_special_field(self, macroname):
        return self.is_removed_field(macroname) or macroname in self.opened_fields

    def child_iterator(self, nodes):
        return ProcessedNodeIterator(
            nodes,
            removed_fields=self.removed_fields,
            opened_fields=self.opened_fields,
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

    def processed_command_definition(self, current_node, child_nodes):
        child_nodes = filter_nodes(child_nodes)
        command_name_node = child_nodes[0].nodelist[0]
        assert isinstance(command_name_node, LatexMacroNode)
        command_name = command_name_node.macroname
        if self.is_special_field(command_name):
            return ""
        return current_node.latex_verbatim()

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
            brenvname = "{" + current_node.environmentname + "}"
            output = (
                "\\begin"
                + brenvname
                + self.get_full_child_str(current_node.nodelist + current_node.nodeargd.argnlist)
                + "\\end"
                + brenvname
            )
        if isinstance(current_node, LatexMacroNode):
            child_nodes = current_node.nodeargd.argnlist
            macroname = current_node.macroname
            if self.is_command_definition(macroname):
                return self.processed_command_definition(current_node, child_nodes)
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
    nodes, _, _ = LatexWalker(latex_str).get_latex_nodes()
    return ProcessedNodeIterator(nodes, **kwargs).get_full_str()
