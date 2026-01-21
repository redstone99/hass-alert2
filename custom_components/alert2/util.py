from   io import StringIO
import logging
import threading
import traceback
#from homeassistant.core import async_get_hass_or_none
_LOGGER = logging.getLogger(__name__)
global_tasks = set()
global_hass = None
DOMAIN = "alert2"
GENERATOR_DOMAIN = "alert2generator"
EVENT_TYPE = 'alert2_report'
gAssertMsg = 'Internal error. Please report to Alert2 maintainers (github.com/redstone99/hass-alert2). Details:'
EVENT_ALERT2_CREATE = 'alert2_create'
EVENT_ALERT2_DELETE  = 'alert2_delete'
EVENT_ALERT2_FIRE = 'alert2_alert_fire'
EVENT_ALERT2_ON = 'alert2_alert_on'
EVENT_ALERT2_OFF = 'alert2_alert_off'
EVENT_ALERT2_ACK = 'alert2_alert_ack'
EVENT_ALERT2_UNACK = 'alert2_alert_unack'
shutting_down = False

class PersistantNotificationHelper:
    Separate = 'separate'
    Collapse = 'collapse'
    CollapseAndDismiss = 'collapse_and_dismiss'
    def genNotificationId(alEnt):
        return f'alert2-dn={alEnt.alDomain}-nm={alEnt.alName}'

#
# report() - report that an event alert has fired.
# 
def report(domain: str, name: str, message: str | None = None, isException: bool = False, withTraceback: str|None = None, escapeHtml: bool = True,
           data: dict = None) -> None:
    evdata = { 'domain' : domain, 'name' : name }
    if message is not None:
        if escapeHtml:
            message = message.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        evdata['message'] = message
    if data is not None:
        evdata['data'] = data
    if withTraceback:
        evdata['traceback'] = withTraceback
    if isException:
        _LOGGER.exception(f'Exception reported: {evdata}')
        #    _LOGGER.exception(f'Exception reported: {evdata}', exc_info=isException)
        evdata['traceback'] = traceback.format_exc()
    else:
        #import traceback
        #_LOGGER.warning(f' err reported from: {"".join(traceback.format_stack())}')
        if domain == DOMAIN and name == 'warning':
            _LOGGER.warning(f'Warning reported: {evdata}')
        else:
            _LOGGER.error(f'Err reported: {evdata}')
    #_LOGGER.warning(f'  report() called from: {"".join(traceback.format_stack())}')
    if shutting_down:
        _LOGGER.warning(f'   Not notifying or further processing alert because HA is shutting donw')
        return
    
    ghass = global_hass
    if ghass and ghass.loop.is_running():
        ghass.loop.call_soon_threadsafe(lambda: ghass.bus.async_fire(EVENT_TYPE, evdata))
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
    #_LOGGER.debug(f'create_task called for domain {domain}, {atask}')
    global_tasks.add(atask)
    return atask

#
# cancel_task - cancel a task created with create_task().  atask is the task returned by create_task()
#
def cancel_task(domain, atask):
    #_LOGGER.debug(f'Calling cancel_task for {domain} and {atask}')
    # Cancelling a task means its done handler is called, so no need to remove task from global_tasks
    atask.cancel()

def taskDone(domain, atask):
    #_LOGGER.debug(f'Calling taskDone for {domain} and {atask}')
    global global_tasks
    if atask in global_tasks:
        #_LOGGER.debug(f'taskDone.. called for domain {domain}, {atask}')
        global_tasks.remove(atask)
    else:
        report(DOMAIN, 'error', f'{gAssertMsg} taskDone called for domain {domain}, {atask} but is not in global_tasks')
    if atask.cancelled():
        #_LOGGER.debug(f'taskDone: task was cancelled: {atask}')
        return
    ex = atask.exception()
    if ex:
        output = StringIO()
        atask.print_stack(file=output)
        astack = output.getvalue()
        _LOGGER.error(f'unhandled_exception with stack {astack}')
        excMsg = f'{ex.__class__}: {ex}. '
        if domain == DOMAIN:
            report(domain, 'global_exception', f'{excMsg}', withTraceback=astack)
        else:
            report(domain, 'unhandled_exception', f'domain={domain} {excMsg}', withTraceback=astack)

def set_shutting_down(abool):
    global shutting_down
    shutting_down = abool
def set_global_hass(ahass):
    global global_hass
    global_hass = ahass
def get_global_hass():
    global global_hass
    return global_hass

