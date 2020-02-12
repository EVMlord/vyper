import ast as python_ast
from typing import (
    Optional,
    Union,
)

import asttokens

from vyper.exceptions import (
    SyntaxException,
)
from vyper.typing import (
    ClassTypes,
)


class AnnotatingVisitor(python_ast.NodeTransformer):
    _source_code: str
    _class_types: ClassTypes

    def __init__(self, source_code: str, class_types: Optional[ClassTypes] = None):
        self._source_code: str = source_code
        self.counter: int = 0
        if class_types is not None:
            self._class_types = class_types
        else:
            self._class_types = {}

    def generic_visit(self, node):
        # Decorate every node in the AST with the original source code. This is
        # necessary to facilitate error pretty-printing.
        node.source_code = self._source_code
        node.node_id = self.counter
        node.ast_type = node.__class__.__name__
        self.counter += 1

        return super().generic_visit(node)

    def visit_ClassDef(self, node):
        self.generic_visit(node)

        # Decorate class definitions with their respective class types
        node.class_type = self._class_types.get(node.name)

        return node

    def visit_Constant(self, node):
        self.generic_visit(node)

        # for python3.8, identify the which Constant based on the value type
        if node.value is None or isinstance(node.value, bool):
            node.ast_type = "NameConstant"
        elif isinstance(node.value, (int, float)):
            node.ast_type = "Num"
        elif isinstance(node.value, str):
            node.ast_type = "Str"
        elif isinstance(node.value, bytes):
            node.ast_type = "Bytes"
        else:
            raise SyntaxException(f"Invalid syntax (unsupported Python Constant AST node).", node)

        return node


class RewriteUnarySubVisitor(python_ast.NodeTransformer):
    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, python_ast.USub) and isinstance(node.operand, python_ast.Num):
            node.operand.n = 0 - node.operand.n
            # NOTE: This is done so that decimal literal now sees the negative sign as part of it
            node.operand.col_offset = node.col_offset
            return node.operand
        else:
            return node


class AddSourceOffsetVisitor(python_ast.NodeTransformer):

    def __init__(self, source_id):
        self._source_id = source_id

    def generic_visit(self, node):
        start = node.first_token.start if hasattr(node, 'first_token') else (None, None)
        end = node.last_token.end if hasattr(node, 'last_token') else (None, None)

        node.lineno = start[0]
        node.col_offset = start[1]
        node.end_lineno = end[0]
        node.end_col_offset = end[1]

        if hasattr(node, 'last_token'):
            start_pos = node.first_token.startpos
            end_pos = node.last_token.endpos
            node.src = f"{start_pos}:{end_pos-start_pos}:{self._source_id}"

        return super().generic_visit(node)


def annotate_python_ast(
    parsed_ast: Union[python_ast.AST, python_ast.Module],
    source_code: str,
    class_types: Optional[ClassTypes] = None,
    source_id: int = 0,
) -> None:
    """
    Performs annotation and optimization on a parsed python AST by doing the
    following:

    * Annotating all AST nodes with the originating source code of the AST
    * Annotating class definition nodes with their original class type
      ("contract" or "struct")
    * Substituting negative values for unary subtractions
    * Annotating all AST nodes with complete source offsets

    :param parsed_ast: The AST to be annotated and optimized.
    :param source_code: The originating source code of the AST.
    :param class_types: A mapping of class names to original class types.
    :return: The annotated and optmized AST.
    """
    AnnotatingVisitor(source_code, class_types).visit(parsed_ast)
    RewriteUnarySubVisitor().visit(parsed_ast)

    asttokens.ASTTokens(source_code, tree=parsed_ast)
    AddSourceOffsetVisitor(source_id).visit(parsed_ast)
