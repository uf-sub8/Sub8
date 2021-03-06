#!/usr/bin/env python
from __future__ import division
import numpy as np
from twisted.internet import defer
from tf import transformations
from txros import action, util, tf, serviceclient
from uf_common.msg import MoveToAction, PoseTwistStamped, Float64Stamped
from sub8 import pose_editor
from sub8_msgs.srv import VisionRequest, VisionRequestRequest, VisionRequest2DRequest, VisionRequest2D
from nav_msgs.msg import Odometry


class VisionProxy(object):
    def __init__(self, service_root, node_handle):
        assert 'vision' in service_root, "expected 'vision' in the name of service_root"
        self._get_2d_service = node_handle.get_service_client(service_root + "/2D", VisionRequest2D)
        self._get_pose_service = node_handle.get_service_client(service_root + "/pose", VisionRequest)

    def get_2d(self, target=''):
        '''Get the 2D projection of the thing
        TODO: Do something intelligent with the stamp
            - This is not "obviously" in any reference frame
            - We'll assume the user knows what they're doing
            - Determine rotation around Z and undo that?

        Camera deprojection stuff should be done elsewhere, this function is for when
            we don't know the depth of the thing we're targeting
        '''
        try:
            pose = self._get_2d_service(VisionRequest2DRequest(target_name=target))
        except(serviceclient.ServiceError):
            return None
        return pose

    def get_pose(self, target='', in_frame=None):
        '''Get the 3D pose of the object we're after
        TODO:
            - Implement in_frame
            - Use the time information in the header
        '''
        try:
            pose = self._get_pose_service(VisionRequestRequest(target_name=target))
        except(serviceclient.ServiceError):
            return None
        except Exception, e:
            print type(e)
        return pose

    @classmethod
    def get_response_direction(self, vision_response):
        xy = np.array([vision_response.pose.x, vision_response.pose.y])
        bounds = np.array([[vision_response.max_x, vision_response.max_y]])
        theta = vision_response.pose.theta
        return (xy - (bounds / 2.0)) / bounds, theta


class _PoseProxy(object):
    def __init__(self, sub, pose, print_only=False):
        self._sub = sub
        self._pose = pose
        self.print_only = print_only

    def __getattr__(self, name):
        def sub_attr_proxy(*args, **kwargs):
            return _PoseProxy(self._sub, getattr(self._pose, name)(*args, **kwargs), print_only=self.print_only)
        return sub_attr_proxy

    def go(self, *args, **kwargs):
        if self.print_only:
            print 'P: {}, Angles: {}'.format(self._pose.position, transformations.euler_from_quaternion(self._pose.orientation))
            return self._sub._node_handle.sleep(0.1)

        goal = self._sub._moveto_action_client.send_goal(self._pose.as_MoveToGoal(*args, **kwargs))
        return goal.get_result()

    def go_trajectory(self, *args, **kwargs):
        traj = self._sub._trajectory_pub.publish(
            self._pose.as_PoseTwistStamped(*args, **kwargs)
        )
        return traj


class _Sub(object):
    def __init__(self, node_handle):
        self._node_handle = node_handle
        self.test_mode = False

    @util.cancellableInlineCallbacks
    def _init(self):
        self._moveto_action_client = yield action.ActionClient(self._node_handle, 'moveto', MoveToAction)
        self._odom_sub = yield self._node_handle.subscribe('odom', Odometry)
        self._trajectory_sub = yield self._node_handle.subscribe('trajectory', PoseTwistStamped)
        self._trajectory_pub = yield self._node_handle.advertise('trajectory', PoseTwistStamped)
        self._dvl_range_sub = yield self._node_handle.subscribe('dvl/range', Float64Stamped)
        self._tf_listener = yield tf.TransformListener(self._node_handle)
        self.channel_marker = VisionProxy('vision/channel_marker', self._node_handle)
        self.buoy = VisionProxy('vision/buoys', self._node_handle)
        self.bin = VisionProxy('vision/bins', self._node_handle)
        defer.returnValue(self)

    def set_test_mode(self):
        self.test_mode = True

    @property
    def pose(self):
        # @forrest: Why trajectory -> last message and not odom??
        # TODO: Make test mode actually change the position of the sub
        last_odom_msg = self._odom_sub.get_last_message()
        if self.test_mode:
            last_odom_msg = Odometry()  # All 0's
        pose = pose_editor.PoseEditor.from_Odometry(last_odom_msg)
        return pose

    @util.cancellableInlineCallbacks
    def last_pose(self):
        last_pose = yield self._odom_sub.get_next_message()
        defer.returnValue(last_pose)

    @property
    def move(self):
        return _PoseProxy(self, self.pose, self.test_mode)

    @util.cancellableInlineCallbacks
    def get_dvl_range(self):
        msg = yield self._dvl_range_sub.get_next_message()
        defer.returnValue(msg.data)

    @util.cancellableInlineCallbacks

    def to_height(self, height, speed=0.1):
        trans = yield self._tf_listener.get_transform(
            '/base_link',
            '/ground',
        )
        delta_height = -(-trans._p[2] - height)
        yield self.move.up(delta_height).go(speed=speed)

    @util.cancellableInlineCallbacks
    def get_in_frame(self, pose_stamped, frame='/map'):
        '''TODO'''
        transform = yield self._tf_listener.get_transform(
            frame,
            pose_stamped.header.frame_id,
            pose_stamped.header.stamp
        )
        tft = tf.Transform.from_Pose_message(pose_stamped.pose)
        full_transform = transform * tft
        position = np.array(full_transform._p)
        orientation = np.array(full_transform._q)

        defer.returnValue([position, orientation])


_subs = {}


@util.cancellableInlineCallbacks
def get_sub(node_handle, need_trajectory=True):
    if node_handle not in _subs:
        _subs[node_handle] = None  # placeholder to prevent this from happening reentrantly
        _subs[node_handle] = yield _Sub(node_handle)._init()
        # XXX remove on nodehandle shutdown
    defer.returnValue(_subs[node_handle])
