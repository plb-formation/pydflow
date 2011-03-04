'''
Created on Mar 4, 2011

@author: tga
'''

from compound import CompoundTask, ChannelPlaceholder
from PyDFlow.base.decorators import task_decorator, TaskWrapper
import logging

class compound(task_decorator):
    def __init__(self, output_types, input_types):
        #output_types = [PlaceholderType(t) for t in output_types]
        super(compound, self).__init__(output_types, input_types)
        self.task_class = CompoundTask
        self.wrapper_class = CompoundWrapper
        

def sub_placeholder(channel_class):
    def place_wrap():
        logging.debug("place_wrap invoked")
        return ChannelPlaceholder(channel_class)
    return place_wrap
 
        
class CompoundWrapper(TaskWrapper):
    def __init__(self, func, task_class, descriptor):
        descriptor.set_output_wrapper(sub_placeholder)
        super(CompoundWrapper, self).__init__(func, task_class, descriptor)