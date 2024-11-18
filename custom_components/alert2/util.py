from   io import StringIO
import logging
import threading
#import traceback
#from homeassistant.core import async_get_hass_or_none
_LOGGER = logging.getLogger(__name__)
global_tasks = set()
global_hass = None
DOMAIN = "alert2"
EVENT_TYPE = 'alert2_report'
gAssertMsg = 'Internal error. Please report to Alert2 maintainers (github.com/redstone99/hass-alert2). Details:'

#
# report() - report that an event alert has fired.
# 
def report(domain: str, name: str, message: str | None = None, isException: bool = False, escapeHtml: bool = True) -> None:
    data = { 'domain' : domain, 'name' : name }
    if message is not None:
        if escapeHtml:
            message = message.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        data['message'] = message
    if isException:
        _LOGGER.exception(f'Exception reported: {data}')
    else:
        _LOGGER.error(f'Err reported: {data}')
    #_LOGGER.warning(f'  report() called from: {"".join(traceback.format_stack())}')
    ghass = global_hass
    if ghass:
        ghass.loop.call_soon_threadsafe(lambda: ghass.bus.async_fire(EVENT_TYPE, data))
    else:
        _LOGGER.error('report() called before Alert2 has initialized. reporting skipped.')

#
# create_task() - similar to hass.async_create_task() but it also report exceptions if they happen so the task doesn't die silently.
#                 Task will be cancelled when HA shuts down.
#                 Should only be called from within the event loop.
# afut is a future
# returns a task object.
#
def create_task(hass, domain, afut):
    atask = hass.async_create_task( afut, eager_start=False )
    return create_task_int(domain, atask)

def create_background_task(hass, domain, afut):
    atask = hass.async_create_background_task( afut, None, eager_start=False )
    return create_task_int(domain, atask)

def create_task_int(domain, atask):
    global global_tasks
    cb = lambda ttask: taskDone(domain, ttask)
    atask.add_done_callback(cb)
    _LOGGER.debug(f'create_task called for domain {domain}, {atask}')
    global_tasks.add(atask)
    return atask

#
# cancel_task - cancel a task created with create_task().  atask is the task returned by create_task()
#
def cancel_task(domain, atask):
    _LOGGER.debug(f'Calling cancel_task for {domain} and {atask}')
    # Cancelling a task means its done handler is called, so no need to remove task from global_tasks
    atask.cancel()

def taskDone(domain, atask):
    _LOGGER.debug(f'Calling taskDone for {domain} and {atask}')
    global global_tasks
    if atask in global_tasks:
        _LOGGER.debug(f'taskDone.. called for domain {domain}, {atask}')
        global_tasks.remove(atask)
    else:
        report(DOMAIN, 'error', f'{gAssertMsg} taskDone called for domain {domain}, {atask} but is not in global_tasks')
    if atask.cancelled():
        _LOGGER.debug(f'taskDone: task was cancelled: {atask}')
        return
    ex = atask.exception()
    if ex:
        output = StringIO()
        atask.print_stack(file=output)
        astack = output.getvalue()
        _LOGGER.error(f'unhandled_exception with stack {astack}')
        if domain == 'alert2':
            report(domain, 'error', f'unhandled_exception: {ex}')
        else:
            report(domain, 'unhandled_exception', str(ex))

def set_global_hass(ahass):
    global global_hass
    global_hass = ahass
def get_global_hass():
    global global_hass
    return global_hass

