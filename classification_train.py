import numpy as np
import PIL
from keras.preprocessing import image
from keras.models import Model
from keras.layers import Dense, GlobalAveragePooling2D, Dropout, Flatten, BatchNormalization
from keras.preprocessing.image import ImageDataGenerator
from keras.utils import to_categorical
from sklearn.svm import SVC
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
from sklearn.metrics import confusion_matrix, classification_report
from sklearn.externals import joblib

classes_list = []

network_input_shape = {
    'vgg16': (224, 224),
    'mobilenet': (224, 224)
}


def process_lines(lines, type):
    """
    lines shape
    /home/tamirmal/workspace/git/tau_proj_prep/TRAIN/IMG_20181226_180908_HHT.jpg 921,1663,1646,2282,0 2066,1459,2698,2002,0 2866,1067,3695,1664,0
    /home/tamirmal/workspace/git/tau_proj_prep/TRAIN/IMG_20181227_001359_HHT.jpg 1717,1431,2721,2151,0
    """
    data = []
    y = []

    visualize = False

    for line in lines:
        img_path = line.split()[0]
        try:
            img = PIL.Image.open(img_path)
            if img is None:
                print("Falied to open {}".format(img_path))
                continue
        except:
            print("Falied to open {}".format(img_path))
            continue

        for box in line.split()[1:]:
            tokens = box.split(',')
            tokens = [int(t) for t in tokens]
            x1, y1, x2, y2 = tokens[0:4]
            gt = tokens[4]
            # need to make the image "square", because it will be reshaped later & we want to maintain the aspect ratio
            h = y2 - y1
            w = x2 - x1
            d = max(h, w)
            x1, y1, x2, y2 = x1, y1, x1 + d, y1 + d
            # crop : left, upper, right, lower
            copy_im = img.copy()
            cropped = copy_im.crop((x1, y1, x2, y2))
            cropped = cropped.resize(network_input_shape[type])
            sample = image.img_to_array(cropped)
            #sample = np.expand_dims(sample, axis=0)

            data.append(sample)
            y.append(gt)

            # Count how much classes we have
            if gt not in classes_list:
                classes_list.append(gt)

            ########## DEBUG HOOKS ############
            if visualize:
                from matplotlib import pyplot
                pyplot.figure()
                pyplot.imshow(cropped)
                pyplot.show()
            ###################################

    data = np.array(data)
    y = np.array(y)
    return data, y
# End

from keras.applications.vgg16 import VGG16
from keras.applications.vgg16 import preprocess_input
from keras.optimizers import SGD
def vgg16_get_model(num_classes):
    vgg = VGG16(weights='imagenet', include_top=False, input_shape=(224,224,3))
    # freeze all layers
    for layer in vgg.layers:
        layer.trainable = False

    vgg.summary()

    print("Using base VGG as feature extractor")
    vgg_features = Model(inputs=vgg.input, outputs=vgg.output)

    x = vgg.output
    x = GlobalAveragePooling2D()(x)
    x = Dense(128, activation='relu')(x)
    x = Dropout(0.5)(x)
    x = Dense(num_classes, activation='softmax', name='predictions')(x)

    my_model = Model(inputs=vgg.input, outputs=x)
    my_model.summary()

    return my_model, vgg_features
# End


def vgg_extract_features_img_array(img_array, model):
    x = np.expand_dims(img_array, axis=0)
    x = preprocess_input(x)
    features = model.predict(x)
    return features
# End


def train_svm(num_classes, dataset):
    train_data, y, val_data, vy = dataset
    # Get models
    net, vgg_features = vgg16_get_model(num_classes)
    # Compile
    sgd = SGD(lr=1e-4, decay=1e-6, momentum=0.9, nesterov=True)
    net.compile(optimizer=sgd, loss='categorical_crossentropy', metrics=['accuracy'])

    print("==========================================")
    print("==== training SVM")
    print("==========================================")

    # define input data generators
    shift = 0.1
    datagen_train = ImageDataGenerator(rotation_range=30, width_shift_range=shift, height_shift_range=shift,
                                       horizontal_flip=True, zoom_range=0.2)
    datagen_train.fit(train_data)

    # For validation, do not rotate. do less augmentation
    shift = 0.05
    datagen_test = ImageDataGenerator(width_shift_range=shift, height_shift_range=shift,
                                      horizontal_flip=True, zoom_range=0.1)
    datagen_test.fit(val_data)

    samples_train = 50 * len(train_data)
    print("Generating {} testing examples, using data aug".format(samples_train))
    svm_x_data = []
    svm_y_data = []
    cnt = 0
    for x_batch, y_batch in datagen_train.flow(train_data, y, batch_size=1):
        svm_x_data.append(vgg_extract_features_img_array(x_batch[0], vgg_features))
        svm_y_data.append(y_batch[0])
        cnt += 1
        if cnt > samples_train:
            break

    svm_x_data = np.array(svm_x_data)
    svm_y_data = np.array(svm_y_data)
    svm_x_data = np.reshape(svm_x_data, (len(svm_x_data), -1))

    param = [
        {
            "kernel": ["linear"],
            "C": [1]
        },
    ]

    # request probability estimation
    svm = SVC(probability=True)
    # 10-fold cross validation, use 4 thread as each fold and each parameter set can be train in parallel
    clf = GridSearchCV(svm, param, cv=4, n_jobs=4, verbose=3)
    # import ipdb; ipdb.set_trace()
    clf.fit(svm_x_data, svm_y_data)
    print("\nBest parameters set:")
    print(clf.best_params_)
    clf = clf.best_estimator_

    print("Run on test set :")
    samples_val = 20 * len(train_data)
    print("Generating {} testing examples, using data aug".format(samples_val))
    val_svm_x_data = []
    val_svm_y_data = []
    cnt = 0
    for x_batch, y_batch in datagen_train.flow(val_data, vy, batch_size=1):
        val_svm_x_data.append(vgg_extract_features_img_array(x_batch[0], vgg_features))
        val_svm_y_data.append(y_batch[0])
        cnt += 1
        if cnt > samples_val:
            break

    val_svm_x_data = np.array(val_svm_x_data)
    val_svm_y_data = np.array(val_svm_y_data)

    val_svm_x_data = np.reshape(val_svm_x_data, (len(val_svm_x_data), -1))
    y_predict = clf.predict(val_svm_x_data)

    print("y predicted")
    print(y_predict)
    print("val svm y data")
    print(val_svm_y_data)
    print("\nConfusion matrix:")
    print(confusion_matrix(val_svm_y_data, y_predict))
    print("\nClassification report:")
    print(classification_report(val_svm_y_data, y_predict))

    out_cls_path = 'svm.dump'
    print("Saving SVM to {}".format(out_cls_path))
    joblib.dump(clf, out_cls_path)
    print("done saving SVM")
    print("End of SVM training")
# End


###############################################
#### Mobilenet
###############################################
from keras.applications import mobilenet
from keras.optimizers import Adam
def mobilenet1_get_model(num_classes):
    base_model = mobilenet.MobileNet(include_top=False, weights='imagenet',
                                     input_shape=(224, 224, 3))
    print("base")
    base_model.summary()

    x = Sequential()
    x.add(base_model)
    x.add(GlobalAveragePooling2D())
    x.add(Dropout(0.5))
    x.add(Dense(512))
    x.add(Dropout(0.5))
    x.add(Dense(num_classes, activation='sigmoid'))
    print("my additions")
    x.summary()
    return x
# End


from keras.models import Sequential
from keras.callbacks import ModelCheckpoint, LearningRateScheduler, EarlyStopping, ReduceLROnPlateau
def train_mobilenet1(dataset, num_classes):
    train_data, y, val_data, vy = dataset

    train_y = to_categorical(y, num_classes)
    val_y = to_categorical(vy, num_classes)
    model = mobilenet1_get_model(num_classes)

    # define input data generators
    shift = 0.1
    datagen_train = ImageDataGenerator(rotation_range=30, width_shift_range=shift, height_shift_range=shift,
                                       horizontal_flip=True, zoom_range=0.2)
    datagen_train.fit(train_data)

    # For validation, do not rotate. do less augmentation
    shift = 0.05
    datagen_test = ImageDataGenerator(width_shift_range=shift, height_shift_range=shift,
                                      horizontal_flip=True, zoom_range=0.1)
    datagen_test.fit(val_data)

    epochs = 100
    batch_size = 32
    steps_per_epoch = int(len(train_data) / batch_size)
    steps_per_epoch_val = int(len(val_data) / batch_size)

    print("len data {}, len val {}".format(len(train_data), len(val_data)))
    print("steps per epoch : {}, val : {}".format(steps_per_epoch, steps_per_epoch_val))

    print("Freezing everything except last 5 layers")
    for layer in model.layers[:-5]:
        layer.trainable = False

    model.compile(optimizer=Adam(lr=1e-4), loss='categorical_crossentropy',
                  metrics=['accuracy', 'mae'])
    model.summary()
    model.fit_generator(datagen_train.flow(train_data, train_y, batch_size=batch_size),
                        steps_per_epoch=steps_per_epoch, epochs=epochs, initial_epoch=0,
                        validation_data=datagen_test.flow(val_data, val_y, batch_size=batch_size),
                        validation_steps=steps_per_epoch_val)

    print("unfreeze all model ...")
    log_dir = 'mobilenet_logs/'
    checkpoint = ModelCheckpoint(log_dir + 'ep{epoch:03d}-loss{loss:.3f}-val_loss{val_loss:.3f}.h5',
                                 monitor='val_loss', save_weights_only=True, save_best_only=True, period=3)
    reduce_lr = ReduceLROnPlateau(monitor='val_loss', factor=0.1, patience=3, verbose=1)
    early_stopping = EarlyStopping(monitor='val_loss', min_delta=0, patience=10, verbose=1)

    for layer in model.layers:
        layer.trainable = True

    model.compile(optimizer=Adam(lr=1e-4), loss='categorical_crossentropy',
                  metrics=['accuracy', 'mae'])
    model.summary()
    model.fit_generator(datagen_train.flow(train_data, train_y, batch_size=batch_size),
                        steps_per_epoch=steps_per_epoch, epochs=2 * epochs, initial_epoch=epochs,
                        validation_data=datagen_test.flow(val_data, val_y, batch_size=batch_size),
                        validation_steps=steps_per_epoch_val,
                        callbacks=[checkpoint, reduce_lr, early_stopping])
    model.save_weights(log_dir + 'mobilenet_trained_weights_final.h5')

# End


def prep_mobilenet(img_array):
    processed_image_mobilenet = mobilenet.preprocess_input(img_array.copy())
    return processed_image_mobilenet

################################################
################################################

def train_post_classifier(lines, idxs_train, idxs_val, type='vgg16'):
    # prepare data
    lines = np.array(lines)
    train_data, y = process_lines(lines[idxs_train], type)
    val_data, vy = process_lines(lines[idxs_val], type)
    num_classes = len(classes_list)
    print("num classes {}".format(num_classes))

#    train_svm(num_classes, [train_data, y, val_data, vy])
    train_mobilenet1([train_data, y, val_data, vy], num_classes)

def predict_class(pil_image, boxes, classifier):
    if (len(boxes) == 0):
        return []

    svm = classifier['svm']
    vgg_features = classifier['net']
    my_mobilenet = classifier['mobilenet']
    x = []
    x_mobilent = []
    for box in boxes:
        # boxes is a list of [top, left, bottom, right] i.e [y1, x1, y2, x2]
        y1, x1, y2, x2 = box  # TODO
        cropped = pil_image.copy()
        # crop : left, upper, right, lower
        cropped = cropped.crop((x1, y1, x2, y2))
        cropped = cropped.resize((224,224))
        cropped = image.img_to_array(cropped)
        x_mobilent.append(cropped)
        features = vgg_extract_features_img_array(cropped, vgg_features)
        x.append(features)

    x = np.reshape(x, (len(boxes), -1))
    x_mobilent = np.reshape(x, (len(boxes), -1))
    x_mobilent = mobilenet.preprocess_input(x_mobilent)

    y = svm.predict(x)
    y_mobilenet = my_mobilenet.predict(x_mobilent)
    return y
# End


def main():
    print('unit testing')
    train_anns = '/home/tamirmal/workspace/git/tau_proj_prep/OUT_yolo_train_zero_based.txt'
    with open(train_anns) as f:
        train_lines = f.readlines()
        print("train len {}".format(len(train_lines)))

    test_anns = '/home/tamirmal/workspace/git/tau_proj_prep/OUT_yolo_test_zero_based.txt'
    with open(test_anns) as f:
        test_lines = f.readlines()
        print("test len {}".format(len(test_lines)))

    lines = list((*train_lines, *test_lines))
    print("lines shape {}".format(len(lines)))

    train_idx = len(train_lines)
    idxs_train = [i for i in range(train_idx)]
    idxs_val = [i for i in range(train_idx, len(lines))]

    train_post_classifier(lines, idxs_train, idxs_val)


if __name__ == "__main__":
    main()
