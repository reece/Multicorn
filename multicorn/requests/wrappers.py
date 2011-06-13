# -*- coding: utf-8 -*-
# Copyright © 2008-2011 Kozea
# This file is part of Multicorn, licensed under a 3-clause BSD license.

import sys
import collections
from . import requests
from .types import Type, Dict, List
from operator import eq


class RequestWrapper(object):
    class_map = {}

    @classmethod
    def register_wrapper(cls, wrapped_class):
        def decorator(wrapper_class):
            cls.class_map[wrapped_class] = wrapper_class
            return wrapper_class
        return decorator

    @classmethod
    def class_from_request_class(cls, request_class):
        for class_ in request_class.mro():
            wrapper_class = cls.class_map.get(class_, None)
            if wrapper_class is not None:
                return wrapper_class
        raise TypeError('No request wrapper for type %s.' % request_class)


    @classmethod
    def from_request(cls, request):
        request = requests.as_request(request)
        return cls.class_from_request_class(type(request))(request)

    def __init__(self, wrapped_request):
        self.wrapped_request = wrapped_request

    def __getattr__(self, name):
        return object.__getattribute__(self.wrapped_request, name)

    def return_type(self, contexts=()):
        """Contexts is a tuple representing the stack of types accessible via context(index)"""
        raise NotImplementedError("return_type is not implemented")

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.wrapped_request)


@RequestWrapper.register_wrapper(requests.StoredItemsRequest)
class StoredItemsWrapper(RequestWrapper):
    def __init__(self, *args, **kwargs):
        super(StoredItemsWrapper, self).__init__(*args, **kwargs)

    def return_type(self, contexts=()):
        return List(self.storage.type)


@RequestWrapper.register_wrapper(requests.LiteralRequest)
class LiteralWrapper(RequestWrapper):
    def __init__(self, *args, **kwargs):
        super(LiteralWrapper, self).__init__(*args, **kwargs)

    def return_type(self, contexts=()):
        return Type(type=type(self.value))


@RequestWrapper.register_wrapper(requests.ListRequest)
class ListWrapper(RequestWrapper):
    def __init__(self, *args, **kwargs):
        super(ListWrapper, self).__init__(*args, **kwargs)
        self.value = [self.from_request(r) for r in self.value]

    def return_type(self, contexts=()):
        if self.value:
            inner_type = self.value[0].return_type(contexts)
            if all((value.return_type(contexts) == inner_type
                for value in self.value)):
                return List(inner_type=inner_type)
        return List(inner_type=Type(type=object))


@RequestWrapper.register_wrapper(requests.TupleRequest)
class TupleWrapper(RequestWrapper):
    def __init__(self, *args, **kwargs):
        super(TupleWrapper, self).__init__(*args, **kwargs)
        self.value = tuple(self.from_request(r) for r in self.value)

    def return_type(self, contexts=()):
        return Type(type=tuple)


@RequestWrapper.register_wrapper(requests.DictRequest)
class DictWrapper(RequestWrapper):
    def __init__(self, *args, **kwargs):
        super(DictWrapper, self).__init__(*args, **kwargs)
        self.value = dict(
            (key, self.from_request(value))
            for key, value in self.value.iteritems())

    def return_type(self, contexts=()):
        mapping = {}
        for key, request in self.value.iteritems():
            mapping[key] = request.return_type(contexts)
        return Dict(mapping=mapping)


@RequestWrapper.register_wrapper(requests.ContextRequest)
class ContextWrapper(RequestWrapper):
    def return_type(self, contexts=()):
        return contexts[self.scope_depth - 1]


@RequestWrapper.register_wrapper(requests.OperationRequest)
class OperationWrapper(RequestWrapper):
    def __init__(self, *args, **kwargs):
        super(OperationWrapper, self).__init__(*args, **kwargs)

        self.subject = self.from_request(self.args[0])
        self.other_args = self.args[1:]
        self.args = (self.subject,) + self.other_args
        self._init_other_args()

    def _init_other_args(self):
        self.other_args = tuple(self.from_request(r) for r in self.other_args)
        self.args = (self.subject,) + self.other_args


@RequestWrapper.register_wrapper(requests.AttributeRequest)
class AttributeWrapper(OperationWrapper):
    def _init_other_args(self):
        attr_name, = self.other_args
        self.attr_name = attr_name  # supposed to be str or unicode

    def return_type(self, contexts=()):
        initial_types = self.subject.return_type(contexts)
        if isinstance(initial_types, Dict):
            return initial_types.mapping[self.attr_name]
        else:
            # If the subject is not an item-like, can't infer anything
            return Type(type=object)


class BooleanOperationWrapper(OperationWrapper):

    def return_type(self, contexts=()):
        return Type(type=bool)

BOOL_OPERATORS = ('and', 'or', 'xor', 'contains', 'eq', 'ne',
                  'lt', 'gt', 'le', 'ge', 'invert')


def defclass(operator, base_class):
    class_name = operator.title() + 'Wrapper'
    request_class = getattr(requests, operator.title() + 'Request')
    class_ = type(class_name, (base_class,), {})
    class_ = RequestWrapper.register_wrapper(request_class)(class_)
    setattr(sys.modules[__name__], class_name, class_)

for operator in BOOL_OPERATORS:
    defclass(operator, BooleanOperationWrapper)

ARITHMETIC_OPERATORS = ('add', 'sub', 'mul', 'floordiv',
                        'div', 'truediv', 'pow', 'mod')


class ArithmeticOperationWrapper(OperationWrapper):

    def return_type(self, contexts=()):
        left_type = self.args[0].return_type(contexts)
        right_type = self.args[1].return_type(contexts)
        return left_type.common_type(right_type)

for operator in ARITHMETIC_OPERATORS:
    defclass(operator, ArithmeticOperationWrapper)


@RequestWrapper.register_wrapper(requests.FilterRequest)
class FilterWrapper(OperationWrapper):
    def _init_other_args(self):
        super(FilterWrapper, self)._init_other_args()
        subject, self.predicate = self.args

    def return_type(self, contexts=()):
        # A filter does not modify its subject
        # assert self.predicate.return_type().type == bool
        return self.subject.return_type(contexts)


@RequestWrapper.register_wrapper(requests.MapRequest)
class MapWrapper(OperationWrapper):
    def _init_other_args(self):
        super(MapWrapper, self)._init_other_args()
        subject, self.operation = self.args

    def return_type(self, contexts=()):
        newcontext = self.subject.return_type(contexts).inner_type
        return List(
            inner_type=self.operation.return_type(contexts + (newcontext,)))


@RequestWrapper.register_wrapper(requests.GroupbyRequest)
class GroupbyWrapper(OperationWrapper):
    def _init_other_args(self):
        super(GroupbyWrapper, self)._init_other_args()
        subject, self.key = self.args

    def return_type(self, contexts=()):
        subject_type = self.subject.return_type(contexts)
        key_type = self.key.return_type(contexts + (subject_type.inner_type,))
        return List(inner_type=Dict(mapping={'grouper': key_type,
            'elements': subject_type}))


@RequestWrapper.register_wrapper(requests.LenRequest)
class LenWrapper(RequestWrapper):

    def return_type(self, contexts=()):
        return Type(type=int)


class PreservingWrapper(OperationWrapper):

    def return_type(self, contexts=()):
        return self.subject.return_type(contexts)


@RequestWrapper.register_wrapper(requests.DistinctRequest)
class DistinctWrapper(PreservingWrapper):
    pass


@RequestWrapper.register_wrapper(requests.SliceRequest)
class SliceWrapper(PreservingWrapper):
    def _init_other_args(self):
        subject, self.slice = self.args


@RequestWrapper.register_wrapper(requests.SortRequest)
class SortWrapper(PreservingWrapper):

    SortKey = collections.namedtuple('SortKey', 'key, reverse')

    def _init_other_args(self):
        super(SortWrapper, self)._init_other_args()
        self.sort_keys = tuple(
            (self.SortKey(sort_key.subject, reverse=True)
             if getattr(sort_key, 'operator_name', '') == 'neg' else
             self.SortKey(sort_key, reverse=False))
            for sort_key in self.other_args)
        self.other_args = self.sort_keys
        self.args = (self.subject,) + self.other_args


class AggregateWrapper(OperationWrapper):

    def return_type(self, contexts=()):
        subject_type = self.subject.return_type(contexts)
        if isinstance(subject_type, List):
            return subject_type.inner_type
        return Type(type == object)


@RequestWrapper.register_wrapper(requests.MaxRequest)
class MaxWrapper(AggregateWrapper):
    pass


@RequestWrapper.register_wrapper(requests.MinRequest)
class MinWrapper(AggregateWrapper):
    pass


@RequestWrapper.register_wrapper(requests.SumRequest)
class SumWrapper(AggregateWrapper):
    pass


@RequestWrapper.register_wrapper(requests.IndexRequest)
class IndexWrapper(AggregateWrapper):
    def _init_other_args(self):
        subject, self.index = self.args
        self.key, = self.other_args  # int, slice, string, ...


@RequestWrapper.register_wrapper(requests.OneRequest)
class OneWrapper(AggregateWrapper):
    def _init_other_args(self):
        self.default, = self.other_args
        if self.default is not None:
            self.default = self.from_request(self.default)

    def return_type(self, contexts=()):
        self.subject_type = super(OneWrapper, self).return_type(contexts)
        if self.default:
            return self.default.return_type(contexts).common_type(
                    self.subject_type)
        else:
            return self.subject_type