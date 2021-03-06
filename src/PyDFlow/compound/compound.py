# Copyright 2010-2011 Tim Armstrong <tga@uchicago.edu>
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
# http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import with_statement
'''
@author: Tim Armstrong
'''
import logging

from PyDFlow.types.logical import Placeholder  
from PyDFlow.base.mutex import graph_mutex
from PyDFlow.writeonce import WriteOnceVar
from PyDFlow.base.flowgraph import Ivar
from PyDFlow.base.atomic import AtomicTask

import threading

from PyDFlow.base.exceptions import *
from PyDFlow.base.states import *
from PyDFlow.types.check import FlTypeError
import time
    
class IvarPlaceholder(Placeholder, Ivar):
    """
    This should have a composite task as input.
    When this is forced, the composite task will construct a new task graph, with the corresponding
    output of te task graph to be grafted into the task graph at the same place as this placeholder.
    
    Assuming that the function does not cause an exception, the steps are:
    1. Identify the ivar placeholders corresponding to the outputs of the composite task
    2. Run the composite task to generate a new task graph, which has the same (or a subset) of the inputs
        to the composite task, and a set of new output ivars corresponding to the placeholders.
    3. Replace the placeholders with the composite tasks in the task graph.  
        The placeholders are updated to point to the original output ivars
    A Composite
    
    TODO: think about what happens if expanding function fails. This ivar should probably
        go into a IVAR_ERROR state.
    """
    def __init__(self, expected_class):
        Placeholder.__init__(self, expected_class)
        Ivar.__init__(self) # Inputs and outputs will be managed
        self._proxy_for = WriteOnceVar()

    def _check_real_ivar(self):
        """
        a) check if the real ivar exists.  return true if found
        b) compress chain of pointers if there are multiple proxies
        """
        ivar = self
        next = self._proxy_for.get()
        
        while isinstance(next, IvarPlaceholder):
            ivar = next
            if next._proxy_for.isSet():
                next = next._proxy_for.get()
            else:
                self._proxy_for = next._proxy_for
                raise Exception("no real ivar found")
        
        self._proxy_for = ivar._proxy_for

    def _replacewith(self, other):
        """
        
        """
        assert(id(self) != id(other))
        logging.debug("_replacewith %s %s" % (repr(self), repr(other)))
        if not self._proxy_for.isSet():
            self._proxy_for.set(other)
            #TODO: does thsi correctly update inputs, outputs?
            
            #for t in self._in_tasks:
            #    t._output_replace(self, other)
            for out in self._out_tasks:
                out._input_replace(self, other)
            other._out_tasks = self._out_tasks 
        else:
            raise Exception("should not be here yet")
            #self._check_real_ivar()
            #self._proxy_for.get()._replacewith(other)
            
    
    def get(self):
        #TODO: check?
        with graph_mutex:
            self._spark()
            self._check_real_ivar()
            next = self._proxy_for.get()
        #TODO: this is a bit hacky...
        return next.get()
        

    def _expand(self, rec=True):
        """
        If rec is true, expand until we hit a real ivar
        Otherwise just do it once 
        """
        if not self._proxy_for.isSet():
            assert len(self._in_tasks) == 1
            in_task = self._in_tasks[0]
            #own_ix = in_task._outputs.index(self)
            in_task._state = T_QUEUED
            graph_mutex.release()
            try:
                in_task._exec(None, None)
            finally:
                graph_mutex.acquire()
            
            assert(self._proxy_for.isSet())
            
            if rec:
                last = self
                ch = self._proxy_for.get()
                while isinstance(ch, IvarPlaceholder):   
                    last = ch
                    ch = ch._expand(rec=False)
                # shorten chain
                self._proxy_for = last._proxy_for
            logging.debug("expanded %s, now points to: %s" % (repr(self), repr(self._proxy_for.get())))
            
        else:
            logging.debug("Proxy for %s" % repr(self._proxy_for))
        return self._proxy_for.get()

    def _spark(self, done_callback=None):
        # input task should be a compound task.
        #  make sure the compound task is expanded
        # TODO: less dreadful implementation
        self._expand()
        
        next_ivar = self._proxy_for.get()
        next_ivar._spark(done_callback)
        
        
    
    def __repr__(self):
        if not self._proxy_for.isSet():
            return "<Placeholder for ivar of type %s>" % repr(self._expected_class)
        else:
            return repr(self._proxy_for.get())
            
    def state(self):
        raise UnimplementedException("state not implemented")
        #TODO
    #TODO: do I need to imp
    def _try_readable(self):
        if self._proxy_for.isSet():
            raise Exception("should not call _try_readable??")
        else:
            return False  
        
class CompoundTask(AtomicTask):
    """
    """
    def __init__(self, func, *args, **kwargs):
        super(CompoundTask, self).__init__(*args, **kwargs)
        self._func = func
        self._compound = True
        
    def _exec(self, continuation, failure_continuation):
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
                #self._prep_ivars()
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
        return_ivars = self._func(*self._inputs)
        try:
            return_ivars[0]
            
        except TypeError:
            return_ivars = [return_ivars]
        if len(return_ivars) != len(self._outputs):
                raise FlTypeError(("%s: Mismatch between number of ivars returned by function " +
                                   " %s and number of ivars expected: %d ") % (repr(self),
                                        repr(return_ivars), len(self._outputs)))
        with graph_mutex:
            # TODO: redundant?
            self._return_ivars = return_ivars
            for i, old, new in zip(range(len(self._outputs)), self._outputs, return_ivars):
                old._replacewith(new) 
                #self._outputs[i] = new
            
            
    def isSynchronous(self):
        return True
