import bson


def is_true(val):
    return bool(val)


def is_false(val):
    return not bool(val)


def int_to_objectid(n):
    s = str(n)
    s = '0' * (24 - len(s)) + s
    return bson.ObjectId(s)


def objectid_to_int(obj):
    return int(str(obj))
