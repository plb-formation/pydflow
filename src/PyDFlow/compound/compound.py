from __future__ import with_statement
'''
Created on Mar 4, 2011

@author: tga
'''
import logging

from PyDFlow.types.logical import Placeholder  
from PyDFlow.base.mutex import graph_mutex
from PyDFlow.base.flowgraph import Channel
from PyDFlow.base.atomic import AtomicTask

from PyDFlow.base.exceptions import *
from PyDFlow.base.states import *
from PyDFlow.types.check import FlTypeError
    
class ChannelPlaceholder(Placeholder, Channel):
    """
    This should have a composite task as input.
    When this is forced, the composite task will construct a new task graph, with the corresponding
    output of te task graph to be grafted into the task graph at the same place as this placeholder.
    
    Assuming that the function does not cause an exception, the steps are:
    1. Identify the channel placeholders corresponding to the outputs of the composite task
    2. Run the composite task to generate a new task graph, which has the same (or a subset) of the inputs
        to the composite task, and a set of new output channels corresponding to the placeholders.
    3. Replace the placeholders with the composite tasks in the task graph.  
        The placeholders are updated to point to the original output channels
    A Composite
    
    TODO: think about what happens if expanding function fails. This channel should probably
        go into a CH_ERROR state.
    """
    def __init__(self, expected_class):
        Placeholder.__init__(self, expected_class)
        Channel.__init__(self) # Inputs and outputs will be managed
        self._proxy_for = None

    def _check_real_channel(self):
        """
        a) check if the real channel exists.  Raise exception otherwise
        b) compress chain of pointers if there are multiple proxies
        """
        chan = None
        next = self._proxy_for
        while next is not None and isinstance(next, ChannelPlaceholder):
            chan = next 
            next = next._proxy_for 
        
        if next is None:
            raise EmptyPlaceholderException("Cannot complete operation: proxy does not point to anything")
        else:
            self._proxy_for = next

    def _replacewith(self, other):
        """
        
        """
        logging.debug("_replacewith %s %s" % (repr(self), repr(other)))
        if self._proxy_for is None:
            self._proxy_for = other
            #TODO: does thsi correctly update inputs, outputs?
            
            for t in self._in_tasks:
                t._output_replace(self, other)
            # TODO: right?
            other._in_tasks = self._in_tasks
        else:
            self._check_real_channel()
            self._proxy_for._replacewith(other)
            
    
    def get(self):
        with graph_mutex:
            self._force()
            self._check_real_channel()
        return self._proxy_for.get()
        

    def _expand(self):
        if self._proxy_for is None:
            assert len(self._in_tasks) == 1
            in_task = self._in_tasks[0]
            #own_ix = in_task._outputs.index(self)
            in_task._state = T_QUEUED
            graph_mutex.release()
            try:
                in_task._exec(None)
            finally:
                graph_mutex.acquire()
            
            #self._proxy_for = in_task._outputs[own_ix]
            logging.debug("expanded %s, new chan is %s" % (repr(self), repr(self._proxy_for)))
        else:
            logging.debug("Proxy for %s" % repr(self._proxy_for))

    def _force(self, done_callback=None):
        # input task should be a compound task.
        #  make sure the compound task is expanded
        # TODO: less dreadful implementation
        self._expand()
        self._check_real_channel()
        self._proxy_for._force(done_callback)
    
    def __repr__(self):
        if self._proxy_for is None:
            return "<Placeholder for channel of type %s>" % repr(self._expected_class)
        else:
            logging.debug("%d %d" % (id(self), id(self._proxy_for)))
            #raise Exception()
            return repr(self._proxy_for)
    def state(self):
        pass
        #TODO
    #TODO: do I need to imp
    
        
class CompoundTask(AtomicTask):
    """
    """
    def __init__(self, func, *args, **kwargs):
        super(CompoundTask, self).__init__(*args, **kwargs)
        self._func = func
        self._compound = True
        
    def _exec(self, continuation):
        """
        Just run the task in the current thread, 
        assuming it is ready
        """
        logging.debug("Starting a CompoundTask %s" % repr(self))
        #TODO: select execution backend, run me!
        
        with graph_mutex:
            # Set things up
            # Check state again to be sure it is sensible
            if self._state == T_QUEUED:
                #self._prep_channels()
                self._state = T_RUNNING
            elif self._state in (T_RUNNING, T_DONE_SUCCESS):
                #TODO: safe I think
                return
            else:
                # Bad state
                # TODO: better logic
                raise Exception("Invalid task state %s encountered by worker thread" % 
                                    (task_state_name[self._state]))
        
        # Run the function in this thread.  If the function raises an exception
        # it will be handled by the caller
        return_chans = self._func(*self._inputs)
        try:
            return_chans[0]
            
        except TypeError:
            return_chans = [return_chans]
        if len(return_chans) != len(self._outputs):
                raise FlTypeError(("%s: Mismatch between number of channels returned by function " +
                                   " %s and number of channels expected: %d ") % (repr(self),
                                        repr(return_chans), len(self._outputs)))
        with graph_mutex:
            self._return_chans = return_chans
            for i, old, new in zip(range(len(self._outputs)), self._outputs, return_chans):
                old._replacewith(new) 
                self._outputs[i] = new
            
            
    def isSynchronous(self):
        return True