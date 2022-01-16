import cv2
import numpy as np
import matplotlib.pyplot as plt
ARUCO_DICT = {
    "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
    "DICT_4X4_100": cv2.aruco.DICT_4X4_100,
    "DICT_4X4_250": cv2.aruco.DICT_4X4_250,
    "DICT_4X4_1000": cv2.aruco.DICT_4X4_1000,
    "DICT_5X5_50": cv2.aruco.DICT_5X5_50,
    "DICT_5X5_100": cv2.aruco.DICT_5X5_100,
    "DICT_5X5_250": cv2.aruco.DICT_5X5_250,
    "DICT_5X5_1000": cv2.aruco.DICT_5X5_1000,
    "DICT_6X6_50": cv2.aruco.DICT_6X6_50,
    "DICT_6X6_100": cv2.aruco.DICT_6X6_100,
    "DICT_6X6_250": cv2.aruco.DICT_6X6_250,
    "DICT_6X6_1000": cv2.aruco.DICT_6X6_1000,
    "DICT_7X7_50": cv2.aruco.DICT_7X7_50,
    "DICT_7X7_100": cv2.aruco.DICT_7X7_100,
    "DICT_7X7_250": cv2.aruco.DICT_7X7_250,
    "DICT_7X7_1000": cv2.aruco.DICT_7X7_1000,
    "DICT_ARUCO_ORIGINAL": cv2.aruco.DICT_ARUCO_ORIGINAL,
    "DICT_APRILTAG_16h5": cv2.aruco.DICT_APRILTAG_16h5,
    "DICT_APRILTAG_25h9": cv2.aruco.DICT_APRILTAG_25h9,
    "DICT_APRILTAG_36h10": cv2.aruco.DICT_APRILTAG_36h10,
    "DICT_APRILTAG_36h11": cv2.aruco.DICT_APRILTAG_36h11
}
ARUCO_SELECT = cv2.aruco.Dictionary_get(ARUCO_DICT["DICT_4X4_50"])


def aruco_detection(image, arucoDict=ARUCO_SELECT, show=False, debug_fig=None, title=""):
    arucoParams = cv2.aruco.DetectorParameters_create()
    (corners, ids, rejected) = cv2.aruco.detectMarkers(image, arucoDict,
                                                       parameters=arucoParams)
    if len(corners) > 0:
        # flatten the ArUco IDs list
        ids = ids.flatten()
        # loop over the detected ArUCo corners
        for (markerCorner, markerID) in zip(corners, ids):

            # extract the marker corners (which are always returned in
            # top-left, top-right, bottom-right, and bottom-left order)
            corners = markerCorner.reshape((4, 2))
            (topLeft, topRight, bottomRight, bottomLeft) = corners

            principal_axis_ = (topLeft - bottomLeft) + (topRight - bottomRight)
            principal_axis = principal_axis_ / np.sqrt(np.sum(principal_axis_ ** 2))
            angle = np.rad2deg(np.arctan2(principal_axis[0], principal_axis[1]))
            print("angle", angle, "principal axis", principal_axis)
            if show or debug_fig is not None:
                # convert each of the (x, y)-coordinate pairs to integers
                topRight = (int(topRight[0]), int(topRight[1]))
                bottomRight = (int(bottomRight[0]), int(bottomRight[1]))
                bottomLeft = (int(bottomLeft[0]), int(bottomLeft[1]))
                topLeft = (int(topLeft[0]), int(topLeft[1]))

                # draw the bounding box of the ArUCo detection
                cv2.line(image, topLeft, topRight, (0, 255, 0), 2)
                cv2.line(image, topRight, bottomRight, (0, 255, 0), 2)
                cv2.line(image, bottomRight, bottomLeft, (0, 255, 0), 2)
                cv2.line(image, bottomLeft, topLeft, (0, 255, 0), 2)

                # compute and draw the center (x, y)-coordinates of the ArUco
                # marker
                cX = int((topLeft[0] + bottomRight[0]) / 2.0)
                cY = int((topLeft[1] + bottomRight[1]) / 2.0)

                cv2.line(image, (cX, cY), (int(cX + principal_axis_[1]), int(cY - principal_axis_[0])), (0, 255, 0), 2)
                cv2.circle(image, (cX, cY), 4, (0, 0, 255), -1)
                # draw the ArUco marker ID on the image
                cv2.putText(image, str(markerID),
                            (topLeft[0], topLeft[1] - 15), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (0, 255, 0), 2)
                # print("[INFO] ArUco marker ID: {}".format(markerID))
                plt.imshow(image)
                plt.title(title + ("angle {}".format(angle)))
                if debug_fig is not None:
                    plt.savefig(debug_fig)
                else:
                    plt.show()
                plt.close()
                return angle, corners
            else:
                return angle, corners
        print("detection failed")
    return None, None


def aruco_chart_generator(arucoDict=ARUCO_SELECT, out=None):  # "ARCUO.png"
    tag_size = 1000
    tag = np.zeros((tag_size, tag_size, 1), dtype="uint8")
    cv2.aruco.drawMarker(arucoDict, 0, tag_size, tag, 1)
    if out is not None:
        cv2.imwrite(out, tag)
    return tag


def aruco_test_image(theta_degrees=0.):
    aruco_tag = aruco_chart_generator()
    img_size = (2000, 2000)
    image = 255 * np.ones((img_size[0], img_size[1], 3))

    # image = 255*np.ones((1000, 1000, 3))
    x_start, y_start = 600, 500
    image[y_start:y_start + aruco_tag.shape[0], x_start:x_start + aruco_tag.shape[1], :] = aruco_tag[::-1, ::-1]

    theta = np.deg2rad(-theta_degrees)
    ho = np.array([
        [np.cos(theta), -np.sin(theta), 0.],
        [np.sin(theta), np.cos(theta), 0.],
        [0., 0., 1.],
    ])
    tr = np.eye(3)
    tr[0, 2] = x_start
    tr[1, 2] = y_start
    ho = np.dot(np.dot(tr, ho), np.linalg.inv(tr))
    image = image.astype(np.uint8)
    image = cv2.warpPerspective(image, ho, (image.shape[1], image.shape[0]))
    # plt.imshow(image)
    # plt.show()
    # cv2.imshow("ArUCo Tag", image)
    # cv2.waitKey(0)
    return image


if __name__ == "__main__":
    theta_degrees = -30.
    image = aruco_test_image(theta_degrees=theta_degrees)
    angle, corn = aruco_detection(image, arucoDict=ARUCO_SELECT, show=True, title="expected %.1f - "%theta_degrees)
    assert np.fabs(angle-theta_degrees)<1., "estimated angle {} differs from expected {}".format(angle, theta_degrees)