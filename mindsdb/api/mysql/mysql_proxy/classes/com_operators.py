import re
import operator


def f_and(*args):
    return all(args)


def f_or(*args):
    return any(args)


def f_like(s, p):
    p = '^{}$'.format(p.replace('%', r'[\s\S]*'))

    return re.match(p, s) is not None


def f_add(*args):
    # strings and numbers are supported
    # maybe it is not true sql-way

    out = args[0] + args[1]
    for i in args[2:]:
        out += i
    return out


def f_ne(a, b):
    return False if a is None or b is None else operator.ne(a, b)


def f_eq(a, b):
    return False if a is None or b is None else operator.eq(a, b)


operator_map = {
    '+': f_add,
    '-': operator.sub,
    '/': operator.truediv,
    '*': operator.mul,
    '%': operator.mod,
    '=': f_eq,
    '!=': f_ne,
    '>': operator.gt,
    '<': operator.lt,
    '>=': operator.ge,
    '<=': operator.le,
    'IS': operator.eq,
    'IS NOT': operator.ne,
    'LIKE': f_like,
    'NOT LIKE': lambda s, p: not f_like(s, p),
    'IN': lambda v, ll: v in ll,
    'NOT IN': lambda v, ll: v not in ll,
    'AND': f_and,
    'OR': f_or,
    '||': f_add
    # binary and, binary not, exists, missing, etc
}
