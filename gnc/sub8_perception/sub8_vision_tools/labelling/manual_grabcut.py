import argparse
import cv2
import pickle
import numpy as np
import sys
from matplotlib import pyplot as plt
"""
TODO:
    - Expand existing pickle feature
"""
class Picker(object):
    # Adaboost http://robertour.com/2012/01/24/adaboost-on-opencv-2-3/

    def __init__(self, image, brush_size=10, initial_mask=None):
        self.brush_size = brush_size
        self.draw_opacity = .5

        self.done = False

        cv2.namedWindow("segment")
        self.image = image

        self.visualize = np.copy(image)
        self.visualize_draw = np.copy(image) * 0
        self.visual_brush_size = np.copy(image) * 0
        if initial_mask is None:
            self.mask = np.zeros(image.shape[:2], dtype=np.uint8)
            self.mask[:, :] = int(cv2.GC_PR_BGD)
        else:
            self.mask = np.ones(image.shape[:2], dtype=np.uint8) * int(cv2.GC_PR_BGD)
            self.mask[initial_mask == int(cv2.GC_FGD)] = int(cv2.GC_FGD)
            self.mask[initial_mask == int(cv2.GC_BGD)] = int(cv2.GC_BGD)
            # self.mask = initial_mask
            self.visualize_draw[self.mask == int(cv2.GC_FGD)] = (0, 200, 0)
            self.visualize_draw[self.mask == int(cv2.GC_BGD)] = (0, 0, 200)


        display = np.array(np.clip(self.visualize + self.visualize_draw * self.draw_opacity, 0, 255), np.uint8)
        cv2.imshow("segment", display)

        self.mouse_state = [0, 0]
        self.opacity_change = None
        self.brush_size_change = None
        self.brush_size_opacity = .4
        cv2.setMouseCallback("segment", self.mouse_cb)
        cv2.waitKey(1)

    def mouse_cb(self, event, x, y, flags, param):
        '''
        Controls:
            L_MSB click to paint green.
            R_MSB click to paint red.
            MIDDLE_MSB to clear paint.
            CTRL then move up and down to change paint opacity.
            SHIFT then move up and down to change brush size. 
        '''
        if self.done:
            return
       
        cv2.circle(self.visual_brush_size, (x,y), self.brush_size, (255, 255, 255), 1) 
        if event == cv2.EVENT_LBUTTONDOWN:
            self.mouse_state[0] = 1
            cv2.circle(self.visualize_draw, (x, y), self.brush_size, (0, 200, 0), -1)
            cv2.circle(self.mask, (x, y), self.brush_size, int(cv2.GC_FGD), -1)

        elif event == cv2.EVENT_LBUTTONUP:
            self.mouse_state[0] = 0

        elif event == cv2.EVENT_RBUTTONDOWN:
            self.mouse_state[1] = 1
            cv2.circle(self.visualize_draw, (x, y), self.brush_size, (0, 0, 200), -1)
            cv2.circle(self.mask, (x, y), self.brush_size, int(cv2.GC_BGD), -1)

        elif event == cv2.EVENT_RBUTTONUP:
            self.mouse_state[1] = 0

        elif event == cv2.EVENT_MBUTTONDOWN:
            self.visualize_draw *= 0
            self.mask = np.ones(self.visualize_draw.shape[:2], dtype=np.uint8) * int(cv2.GC_PR_BGD)

        elif event == cv2.EVENT_MOUSEMOVE:
            if flags == cv2.EVENT_FLAG_CTRLKEY:
                if self.opacity_change is None:
                    self.opacity_change = y
                self.draw_opacity = np.clip((self.draw_opacity + (self.opacity_change - y) * .005), 0, 1)
                self.opacity_change = y

            elif flags == cv2.EVENT_FLAG_SHIFTKEY:
                if self.brush_size_change is None:
                    self.brush_size_change = y
                self.brush_size = np.clip((self.brush_size + (self.brush_size_change - y)), 0, 99)
                self.brush_size_change = y
                self.brush_size_opacity = .9

            else:
                self.opacity_change = None
                if self.mouse_state[0]:
                    cv2.circle(self.visualize_draw, (x, y), self.brush_size, (0, 200, 0), -1)
                    cv2.circle(self.mask, (x, y), self.brush_size, int(cv2.GC_FGD), -1)

                elif self.mouse_state[1]:
                    cv2.circle(self.visualize_draw, (x, y), self.brush_size, (0, 0, 200), -1)
                    cv2.circle(self.mask, (x, y), self.brush_size, int(cv2.GC_BGD), -1)

        display = np.array(np.clip(self.visualize + self.visualize_draw * self.draw_opacity + 
                                   self.visual_brush_size * self.brush_size_opacity, 0, 255), np.uint8)
        cv2.imshow("segment", display)
        self.visual_brush_size *= 0
        self.brush_size_opacity = .4

    def wait_for_key(self, keys):
        print 'press one of:', keys
        while(not rospy.is_shutdown()):
            key = chr(cv2.waitKey(50) & 0xFF)
            if key in keys:
                return key

    def get_biggest_ctr(self, image):
        contours, _ = cv2.findContours(np.copy(image), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        if len(contours) > 0:
            cnt = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(cnt)
            M = cv2.moments(cnt)
            cx = int(M['m10'] / M['m00'])
            cy = int(M['m01'] / M['m00'])
            tpl_center = (int(cx), int(cy))
            return cnt
        else:
            return None

    def segment(self):
        print 'Keys:'
        print '\tPress "space" to skip the current image'
        print '\tPress "q" to quit and save your previous segmentations'
        print '\tPress w to run segmentation on the image'
        key = self.wait_for_key(' qnw')
        if key in [' ', 'q']:
                return None, None, key
        self.done = True

        bgdModel = np.zeros((1, 65), np.float64)
        fgdModel = np.zeros((1, 65), np.float64)

        out_mask = np.copy(self.mask)
        
        print 'Segmenting...'
        if out_mask[out_mask == 1].size == 0:
            # Nothing was selected
            print "Nothing was selected, continuing."
            return None, None, key

        cv2.grabCut(
            self.image,
            out_mask,
            None,
            bgdModel,
            fgdModel,
            1,
            cv2.GC_INIT_WITH_MASK
        )

        return_mask = np.zeros(out_mask.shape).astype(np.float64)
        display_mask = np.ones(out_mask.shape).astype(np.float64) * 0.1
        bgnd = (out_mask == cv2.GC_PR_BGD) | (out_mask == cv2.GC_BGD)

        ctr = self.get_biggest_ctr(np.logical_not(bgnd).astype(np.uint8))

        if ctr is not None:
            cv2.drawContours(display_mask, [ctr], -1, 1, -1)
            cv2.drawContours(return_mask, [ctr], -1, 1, -1)

        display = display_mask[:, :, np.newaxis] * self.image.astype(np.float64)
        cv2.imshow('segment', display / np.max(display))

        cv2.imshow('all', np.logical_not(bgnd).astype(np.uint8) * 255)
        print 'Keys:'
        print '\tPress "space" to skip the current segmentation'
        print '\tPress "q" to quit and save all segmentations including this'
        print '\tPress w record this segmentation and move on to the next image'
        key = self.wait_for_key('qnzw ')
        if key in [' ', 'q']:
            return None, None, key

        return out_mask, return_mask, key

    def save(self, mask):
        data = {"image": self.image, 'classes': mask}
        pickle.dump(data, open("save.p", "wb"))


if __name__ == '__main__':
    usage_msg = ("Pass the path to a bag or the start of an image sequence, and we'll crawl through the images in it")
    desc_msg = "A tool for making manual segmentation fun! I am sorry the keyboard shortcuts are nonsense"

    parser = argparse.ArgumentParser(usage=usage_msg, description=desc_msg)
    parser.add_argument(dest='file_name',
                        help="Either the name of the bag or first image in a sequence you'd like to segment.")
    parser.add_argument('--topic', type=str, help="Name of the topic to use or the usb camera number.")
    parser.add_argument('--append', type=str, help="Path to a file to append to.")
    parser.add_argument('--output', type=str, help="Path to a file to output to (and overwrite)",
                        default='segments.p')
    parser.add_argument('--brush_size', type=int, help="Brush size",
                        default=3)

    args = parser.parse_args(sys.argv[1:])

    if args.append is None:
        print 'Creating new pickle'
        data = []
    else:
        args.output = args.append
        data = pickle.load(open(args.append, "rb"))

    file_name = args.file_name
    if file_name.split('.')[-1] == 'bag':
        import rospy
        import bag_crawler
        bc = bag_crawler.BagCrawler(file_name)
        print bc.image_topics[0]
    else:
        # Assuming we don't have ros installed, so make our own ros for rospy.is_shutdown()
        class rospy():
            @classmethod
            def is_shutdown(self):
                return False

        import image_crawler        
        if file_name == 'video':
            bc = image_crawler.VideoCrawler(file_name, args.topic)
        else:
            bc = image_crawler.ImageCrawler(file_name)

    last_mask = None
    num_imgs = len(data)

    if args.topic is not None:
        assert args.topic in bc.image_topics, "{} not in the bag".format(args.topic)
        print 'Crawling topic {}'.format(args.topic)
        crawl = bc.crawl(topic=args.topic)
    else:
        crawl = bc.crawl(topic=bc.image_topics[0])

    for image in crawl:
        num_imgs += 1
        print 'On image #{}'.format(num_imgs)
        p = Picker(image, brush_size=args.brush_size, initial_mask=last_mask)
        last_mask, last_targets, key = p.segment()
        if key == 'q':
            break
        elif key == ' ':
            print 'ignoring image'
            continue
        elif key == 'z':
            print 'saving output'
            pickle.dump(data, open(args.output, 'wb'))

        print 'recording'
        data.append((image, last_targets))

    print 'saving output'
    pickle.dump(data, open(args.output, 'wb'))
